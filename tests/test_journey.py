"""Calendar history, stale buttons, resumable check-ins and atomic migration."""
import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault('BOT_TOKEN', '123456789:' + 'A' * 35)
os.environ.setdefault('ALLOWED_CHAT_ID', '123456789')

from bot import db, journey, messages, planner, handlers, telegraph
from bot.bridge import bridge, refresh_morning
from bot.content.articles import ARTICLES, article_digest
from bot.max_bot import MaxBot, kb_to_max
from bot.vk_bot import VKBot, kb_to_vk
from bot.scheduler import BotScheduler

TODAY = '2026-09-11'


def callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]


def choice(kb, value):
    return next(c for c in callbacks(kb) if c.endswith(':' + value))


class JourneyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite')
        db._write_lock = asyncio.Lock()
        journey._lock = asyncio.Lock()
        self.clock = patch('bot.planner.now', return_value=datetime(2026, 9, 11, 20, 30, tzinfo=ZoneInfo('Europe/Moscow')))
        self.clock.start()
        await db.init_db(self.path)

    async def asyncTearDown(self):
        await db.close_db()
        self.clock.stop()
        self.temp.cleanup()

    async def finish(self, pain='1', movement='partial', reading='yes'):
        _, kb = await journey.evening()
        for value in (pain, movement, reading):
            _, kb = await journey.action(choice(kb, value))
        return kb

    async def test_browsing_old_lesson_never_moves_program_or_old_dates(self):
        await db.continue_program(20, TODAY)
        before = await db.get_state()
        await journey.lesson('3')
        await journey.action('learn:open:3')
        await journey.action('learn:done:3:' + TODAY)
        self.assertEqual(before, await db.get_state())
        self.assertEqual((await db.reading_status(3))['read_at'], TODAY)
        self.assertIsNone(await db.get_log(TODAY))
        self.assertEqual(await db.readings_between('2026-09-01', '2026-09-10'), [])
        self.assertIn('11.09', await journey.report())

    async def test_reading_resume_and_partial_survive_restart(self):
        await journey.action('learn:page:1:1')
        await db.close_db()
        await db.init_db(self.path)
        text, kb = await journey.action('learn:open:1')
        self.assertIn('Фрагмент 2', text)
        self.assertEqual((await db.reading_status(1))['page'], 1)
        self.assertEqual((await db.readings_between(TODAY, TODAY))[0]['status'], 'partial')
        self.assertNotIn(1, await db.read_days())
        await journey.action('learn:done:1:' + TODAY)
        await journey.action('learn:page:1:0')
        self.assertEqual((await db.readings_between(TODAY, TODAY))[0]['status'], 'done')

    async def test_continue_is_explicit_preserves_history_and_pins_this_morning(self):
        await db.mark_read(2, TODAY)
        _, kb = await journey.evening()
        old_button = choice(kb, '2')
        await journey.continue_from('8')
        state = await db.get_state()
        self.assertEqual(state['current_day'], 8)
        self.assertEqual(await planner.morning_rollover(state, 'Europe/Moscow'), {})
        self.assertEqual(await db.read_days(), {2})
        await journey.action(old_button)
        self.assertIsNone(await db.get_checkin(TODAY))

    async def test_draft_is_not_a_report_and_survives_restart(self):
        _, kb = await journey.evening()
        _, movement = await journey.action(choice(kb, '2'))
        self.assertIsNone(await db.get_log(TODAY))
        self.assertIn('Вечерних записей: 0/7', await journey.report())
        await db.close_db()
        await db.init_db(self.path)
        _, resumed = await journey.evening()
        self.assertEqual(callbacks(resumed), callbacks(movement))

    async def test_concurrent_duplicate_answers_count_once(self):
        _, kb = await journey.evening()
        pain = choice(kb, '1')
        results = await asyncio.gather(journey.action(pain), journey.action(pain))
        movement = next(k for _, k in results if k is not None)
        _, reading = await journey.action(choice(movement, 'partial'))
        final = choice(reading, 'yes')
        await asyncio.gather(journey.action(final), journey.action(final))
        log = await db.get_log(TODAY)
        self.assertEqual((log['pain'], log['pain_scale'], log['habits_done'], log['habits_status'], log['evening_done']), (1, 3, 0, 'partial', 1))
        self.assertEqual((await db.get_state())['streak'], 1)
        self.assertEqual(len(await db.readings_between(TODAY, TODAY)), 1)
        await journey.action(pain)
        self.assertEqual((await db.get_checkin(TODAY))['step'], 'done')

    async def test_edit_replaces_only_when_finished_and_rejects_old_generation(self):
        kb = await self.finish()
        original = await db.get_log(TODAY)
        edit = choice(kb, 'start')
        _, new = await journey.action(edit)
        await journey.action(edit)  # old edit token no longer applies
        _, move = await journey.action(choice(new, '0'))
        self.assertEqual(await db.get_log(TODAY), original)
        _, read = await journey.action(choice(move, 'no'))
        await journey.action(choice(read, 'no'))
        self.assertEqual((await db.get_log(TODAY))['pain'], 0)
        self.assertEqual((await db.get_state())['streak'], 1)
        self.assertEqual(await db.read_days(), {1})  # editing a survey cannot erase reading history

    async def test_partial_reading_visible_but_not_completed(self):
        await self.finish(reading='partial')
        report = await journey.report()
        self.assertIn('чтение начато', report)
        self.assertIn('Дней с чтением: 0/7', report)
        self.assertEqual(await db.read_days(), set())

    async def test_stale_date_and_malformed_callbacks_do_not_write(self):
        for data in ['learn:done:1:2026-09-10', 'move:2026-09-10:1', 'check:2026-09-10:1:abcd:pain:3', 'check:', 'learn:open:99', 'learn:page:x:y', 'move:x:1', 'learn:done:1', 'check:2026-09-11:1:pain:3']:
            with self.subTest(data=data):
                await journey.action(data)
        self.assertEqual(await db.read_days(), set())
        self.assertIsNone(await db.get_log(TODAY))
        self.assertIsNone(await db.get_checkin(TODAY))

    async def test_bad_arguments_and_report_underflow(self):
        before = await db.get_state()
        for arg in ['0', '31', '-1', '1.0', '１２', '1'*5000, '5 extra']:
            self.assertIsNone(journey.day_argument(arg))
            await journey.continue_from(arg)
        for arg in ['0001-01-01', '20260911', '2026-W37-5', '2026-09-12', 'invalid']:
            self.assertIn('Укажи дату', await journey.report(arg))
        self.assertEqual(before, await db.get_state())

    async def test_legacy_pain_retains_raw_value_but_is_not_averaged(self):
        await db.upsert_log('2026-09-10', 5, pain=8, habits_done=True, evening_done=True)
        await self.finish(pain='0', movement='no', reading='no')
        text = await journey.report()
        self.assertIn('8 (ранняя запись)', text)
        self.assertIn('средняя 0.0 из 3', text)
        self.assertIn('Вечерних записей: 2/7', text)
        self.assertIn('движение отмечено ранее', text)
        self.assertIn('06.09 · боль —', text)

    async def test_migration_is_repeatable_and_preserves_original_tables(self):
        await db.close_db()
        Path(self.path).unlink()
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript('''CREATE TABLE daily_logs (date TEXT PRIMARY KEY, day_number INTEGER NOT NULL, pain INTEGER, stiffness INTEGER, morning_done INTEGER DEFAULT 0, evening_done INTEGER DEFAULT 0, habits_done INTEGER DEFAULT 0, note TEXT);
            INSERT INTO daily_logs VALUES ('2026-08-31', 17, 7, 9, 1, 1, 1, 'original note');''')
        await db.init_db(self.path)
        await db.close_db()
        await db.init_db(self.path)
        row = await db.get_log('2026-08-31')
        self.assertEqual((row['day_number'], row['pain'], row['stiffness'], row['note']), (17, 7, 9, 'original note'))
        self.assertIsNone(row['pain_scale'])
        self.assertIsNone(row['habits_status'])

    async def test_atomic_completion_rolls_back_if_reading_write_fails(self):
        _, kb = await journey.evening()
        _, kb = await journey.action(choice(kb, '1'))
        _, kb = await journey.action(choice(kb, 'yes'))
        await db._conn().executescript("CREATE TRIGGER fail_reading BEFORE INSERT ON reading_events BEGIN SELECT RAISE(ABORT, 'test failure'); END;")
        with self.assertRaises(sqlite3.IntegrityError):
            await journey.action(choice(kb, 'yes'))
        await db.set_channel('tg', muted=False)  # unrelated commit cannot persist a partial survey
        self.assertIsNone(await db.get_log(TODAY))
        self.assertEqual((await db.get_state())['streak'], 0)
        self.assertEqual((await db.get_checkin(TODAY))['step'], 'reading')
        await db._conn().execute('DROP TRIGGER fail_reading')
        await journey.action(choice(kb, 'yes'))
        self.assertEqual((await db.get_log(TODAY))['evening_done'], 1)

    async def test_old_completed_log_requires_explicit_edit_on_every_open(self):
        await db.upsert_log(TODAY, 7, pain=2, evening_done=True)
        for _ in range(2):
            text, kb = await journey.evening()
            self.assertIn('сохранена', text)
            self.assertTrue(any(':edit:' in x for x in callbacks(kb)))
            self.assertFalse(any(':pain:' in x for x in callbacks(kb)))

    async def test_reset_preserves_history_and_invalidates_pending_buttons(self):
        await db.mark_read(7, TODAY)
        _, kb = await journey.evening()
        await journey.reset()
        await journey.action(choice(kb, '3'))
        self.assertIsNone(await db.get_checkin(TODAY))
        self.assertEqual(await db.read_days(), {7})
        self.assertEqual((await db.get_state())['current_day'], 1)

    async def test_tg_vk_max_share_same_checkin_and_reports(self):
        _, pain = await journey.evening()
        msg = SimpleNamespace(answer=AsyncMock())
        cb = SimpleNamespace(data=choice(pain, '1'), answer=AsyncMock(), message=msg)
        await handlers.cb_journey(cb)
        movement = msg.answer.call_args.kwargs['reply_markup']
        vk = VKBot('test', 42)
        with patch.object(vk, '_reply', new_callable=AsyncMock) as reply, patch.object(vk, '_answer_event', new_callable=AsyncMock):
            await vk._on_event(dict(peer_id=42, user_id=42, conversation_message_id=1, event_id='x', payload=json.dumps(choice(movement, 'partial'))))
            reading = reply.call_args.args[1]
        mx = MaxBot('test')
        mx.owner_chat_id = '42'
        with patch.object(mx, '_reply', new_callable=AsyncMock), patch.object(mx, '_answer_cb', new_callable=AsyncMock):
            await mx._on_callback(dict(callback_id='x', payload=choice(reading, 'yes'), user={'user_id': 42}, message={'recipient': {'chat_id': 42}}))
        self.assertEqual((await db.get_log(TODAY))['habits_status'], 'partial')
        await handlers.cmd_report(SimpleNamespace(text='/report', answer=msg.answer))
        self.assertIn('Вечерних записей: 1/7', msg.answer.call_args.args[0])

    async def test_scheduler_uses_same_checkin_draft(self):
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)))
        scheduler = BotScheduler(bot, 42)
        await scheduler._send_evening()
        payload = bot.send_message.call_args.kwargs['reply_markup']
        _, resumed = await journey.evening()
        self.assertEqual(callbacks(payload), callbacks(resumed))

    async def test_weekly_retry_does_not_resend_morning(self):
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)))
        scheduler = BotScheduler(bot, 42)
        await db.mark_sent(TODAY, 'morning')
        with patch('bot.planner.is_sunday', return_value=True), patch.object(scheduler, '_send', new_callable=AsyncMock) as send:
            await scheduler._send_morning()
            self.assertIn('Неделя', send.call_args.args[0])
            await scheduler._send_morning()
            self.assertEqual(send.await_count, 1)

    async def test_upload_updates_stale_links_and_skips_current_versions(self):
        from scripts import upload_telegraph
        await db.set_telegraph_links([(2, 'https://telegra.ph/current', ARTICLES[1]['title'])])
        await db._conn().execute("INSERT INTO telegraph_links(day, url, title) VALUES (1, 'https://telegra.ph/old', 'old')")
        await db._conn().commit()
        # Uploader owns its DB connection and must release it on completion.
        await db.close_db()
        conf = SimpleNamespace(db_path=self.path, telegraph_token='test')
        with patch.object(upload_telegraph, 'config', conf), patch.object(upload_telegraph, 'ARTICLES', ARTICLES[:2]), patch.object(upload_telegraph, '_PAGE_DELAY', 0), patch.object(upload_telegraph, 'check_image_urls', new_callable=AsyncMock), patch.object(upload_telegraph, 'create_page', new_callable=AsyncMock, return_value='https://telegra.ph/new') as create, patch('builtins.print'):
            await upload_telegraph.main()
            self.assertEqual(create.await_count, 1)
        await db.init_db(self.path)
        self.assertEqual(await db.get_telegraph_link(1), 'https://telegra.ph/new')
        self.assertEqual(await db.get_telegraph_link(2), 'https://telegra.ph/current')

    async def test_movement_sync_preserves_reading_buttons(self):
        text, _ = messages.morning_text(1, None)
        await db.set_msg_ref(TODAY, 'morning', 'tg', '42', '1', text)
        tg = SimpleNamespace(edit_message_reply_markup=AsyncMock())
        with patch.object(bridge, 'tg', tg):
            await refresh_morning(TODAY)
        args = tg.edit_message_reply_markup.call_args.kwargs
        self.assertEqual(args['chat_id'], 42)
        self.assertTrue(any(x.startswith('learn:') for x in callbacks(args['reply_markup'])))
        self.assertFalse(any(x.startswith('move:') for x in callbacks(args['reply_markup'])))

    async def test_telegraph_link_only_used_for_current_content(self):
        await db._conn().execute("INSERT INTO telegraph_links(day, url, title) VALUES (1, 'https://telegra.ph/old', 'old')")
        await db._conn().commit()
        self.assertIsNone(await db.get_telegraph_link(1))
        await db.set_telegraph_links([(1, 'https://telegra.ph/new', ARTICLES[0]['title'])])
        self.assertEqual(await db.get_telegraph_link(1), 'https://telegra.ph/new')

    async def test_all_lesson_lists_fit_vk_rows_and_include_thirty_topics(self):
        days = []
        for page in range(6):
            _, kb = await journey.lesson_list(page)
            self.assertLessEqual(len(kb.inline_keyboard), 6)
            days.extend(int(c.split(':')[2]) for c in callbacks(kb) if c.startswith('learn:card:'))
        self.assertEqual(days, list(range(1, 31)))


class ContentTests(unittest.TestCase):
    def test_all_lessons_render_with_media_and_transport_limits(self):
        self.assertEqual([a['day'] for a in ARTICLES], list(range(1, 31)))
        for a in ARTICLES:
            with self.subTest(day=a['day']):
                for field in ['title', 'teaser', 'green', 'action', 'body_markdown', 'sources', 'video', 'image']:
                    self.assertTrue(a[field])
                self.assertNotRegex(json.dumps(a, ensure_ascii=False).lower(), r'дот[ауы]|dota|катк')
                self.assertTrue(Path(a['image']['path']).is_file())
                outputs = [messages.morning_text(a['day'], 'https://example.org/article'), messages.theory_text(a['day'], 'https://example.org/article', read_at=TODAY)]
                outputs += [messages.lesson_page_text(a['day'], n, 'https://example.org/article') for n in range(len(messages.lesson_pages(a['day'])))]
                for text, kb in outputs:
                    self.assertLessEqual(len(text.encode('utf-16-le')) // 2, 4000)
                    self.assertLessEqual(len(kb.inline_keyboard), 6)
                    for c in callbacks(kb):
                        self.assertLessEqual(len(c.encode()), 64)
                    self.assertTrue(json.loads(kb_to_vk(kb))['inline'])
                    self.assertTrue(kb_to_max(kb))
                nodes = telegraph.article_to_content(a)
                self.assertIn(a['video']['url'], json.dumps(nodes))
                self.assertIn(a['image']['url'], json.dumps(nodes))
                self.assertLess(len(json.dumps(nodes).encode()), 64 * 1024)

    def test_sparkline_uses_entire_zero_to_three_scale(self):
        self.assertEqual(planner.sparkline([0, None, 1, 2, 3]), '▁·▃▆█')
