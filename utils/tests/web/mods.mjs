// A mod's file for the Node tests (plan mod-repos 2.3). relay, lcpp, tts and gen3d are submodules,
// empty in a clone made without them: `skip` says why, and `load` gives null instead of failing.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

export function modSkip(...files) {
  const missing = files.filter(f => !fs.existsSync(path.join(root, f)));
  if (!missing.length) return false;
  const dirs = [...new Set(missing.map(f => f.split('/').slice(0, 2).join('/')))];
  return `${dirs.join(', ')} ${dirs.length === 1 ? "isn't" : "aren't"} checked out: git submodule update --init ${dirs.join(' ')}`;
}

export const loadMod = async f => (modSkip(f) ? null : import(pathToFileURL(path.join(root, f)).href));
