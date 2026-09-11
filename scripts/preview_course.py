"""Render the checked-in course for offline editorial review; no DB or network writes."""
from __future__ import annotations

import argparse
import html
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot.content.articles import ARTICLES
from bot.telegraph import article_to_content


def node_html(node):
    if isinstance(node, str):
        return html.escape(node)
    tag = node['tag']
    attrs = ''.join(f' {key}="{html.escape(value, quote=True)}"' for key, value in node.get('attrs', {}).items())
    children = ''.join(node_html(c) for c in node.get('children', []))
    return f'<{tag}{attrs}>' if tag in ('img', 'br', 'hr') else f'<{tag}{attrs}>{children}</{tag}>'


def render(output: Path):
    links, chapters = [], []
    for article in ARTICLES:
        day = article['day']
        links.append(f'<a href="#day-{day}">{day}. {html.escape(article["title"])}</a>')
        nodes = article_to_content(article)
        # Local image paths let reviewers see unpublished assets too.
        nodes[0]['children'][0]['attrs']['src'] = os.path.relpath(ROOT / article['image']['path'], output.parent)
        chapters.append(f'<article id="day-{day}"><div class="day">День {day}</div><h1>{html.escape(article["title"])}</h1>'
                        f'<p class="teaser">{html.escape(article["teaser"])}</p>'
                        + ''.join(node_html(n) for n in nodes) + '<a href="#top">К темам ↑</a></article>')
    page = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Движение в обычном дне — 30 коротких уроков</title><style>
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f6f4ef;color:#263e3d;font:18px/1.65 system-ui,sans-serif}header{padding:56px 24px 24px;max-width:900px;margin:auto}header h1{font-size:36px;line-height:1.2}nav{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:24px}nav a{padding:10px 14px;background:#fff;border-radius:10px;font-size:15px}a{color:#16766a;text-decoration:none}a:hover{text-decoration:underline}main{max-width:900px;margin:auto;padding:24px}article{background:#fff;border-radius:20px;padding:40px;margin:0 0 32px;scroll-margin-top:20px}h1{font-size:30px;line-height:1.25}h3{font-size:23px;line-height:1.3;margin-top:32px}.day{font-size:14px;letter-spacing:.08em;text-transform:uppercase;color:#64837f}.teaser{font-size:21px;color:#64837f}figure{margin:28px 0}img{width:100%;border-radius:12px}figcaption{font-size:14px;color:#64837f}article>a{font-size:15px}@media(max-width:640px){nav{grid-template-columns:1fr}article{padding:22px}main{padding:12px}h1{font-size:26px}}
</style><header id="top"><div class="day">30 коротких уроков</div><h1>Движение в обычном дне</h1><p>Выбери интересную тему, прочитай и попробуй одно посильное действие.</p><nav>'''
    page += ''.join(links) + '</nav></header><main>' + ''.join(chapters) + '</main></html>'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/body-course-preview.html'))
    args = parser.parse_args()
    render(args.output.resolve())
    print(args.output.resolve())
