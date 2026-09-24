import fs from 'node:fs';
import assert from 'node:assert/strict';

// Packaging contract only. Native behavior is independently tested on Windows.
for (const file of ['launcher.py', 'launch-hidden.vbs', 'scripts/install.ps1', 'scripts/install-shortcuts.ps1']) {
  const source = fs.readFileSync(file, 'utf8');
  assert(!source.includes('\ufffd'), `${file}: invalid UTF-8`);
  assert(!/C:[\\/]+Users[\\/]+jedia/i.test(source), `${file}: machine-specific path`);
  assert(source.length > 0, `${file}: empty file`);
}
console.log('Portable source contract passed; native startup/shortcut tests run separately.');
