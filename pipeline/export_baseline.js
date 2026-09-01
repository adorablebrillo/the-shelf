#!/usr/bin/env node
// Export the design template's built-in book data into curated-month files
// (build.py input schema) so the Docker image can bake a real default shelf.
// Usage: node export_baseline.js pipeline/template.html pipeline/baseline
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const script = html.match(/<script>\n\(function\(\)\{[\s\S]*?\n<.*/)[0];

function grab(name) {
  const m = script.match(new RegExp('var ' + name + '=([\\s\\S]*?);\\s*\n'));
  if (!m) throw new Error('missing ' + name);
  return eval('(' + m[1] + ')');
}

const BOOKS = grab('BOOKS');
const MONTHS = grab('MONTHS');
const out = process.argv[3];
fs.mkdirSync(out, { recursive: true });

for (const [key, mm] of Object.entries(MONTHS)) {
  if (key === 'sep') continue; // the design's demo month; the drop semantics start with jun/aug
  const ym = key === 'jun' ? '2026-06' : key === 'jul' ? '2026-07' : '2026-08';
  const books = mm.books.map((id) => BOOKS[id] || null).filter(Boolean).map((b) => ({
    id: b.id || idOf(b),
    title: b.title,
    author: b.author,
    publisher: b.publisher || '',
    date: b.date || '',
    genre: b.genre || '',
    spice: b.spice || 3,
    rating: b.gr || 0,
    hook: b.hook || '',
    tropes: b.tropes || [],
    formats: b.formats || ['ebook'],
    img: b.img || '',
    mmc: b.mmc || { score: 3, archetype: 'same energy, no magic' },
    fresh: !!b.fresh, aseq: !!b.aseq,
  }));
  const cur = {
    month: ym,
    label: mm.label || ym,
    top_pick: mm.topPick && mm.books.includes(mm.topPick) ? mm.topPick : (books[0] && books[0].id),
    books,
  };
  fs.writeFileSync(out + '/month-' + ym + '.json', JSON.stringify(cur, null, 1));
  console.log('wrote', ym, '-', books.length, 'books');
}

function idOf(b) {
  return (b.title + '-' + b.author).toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
}
