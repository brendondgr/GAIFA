// Imports a module of the Calendar page (services/calendar/ui/) by file URL.
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
const ui = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../ui');
export const load = name => import(pathToFileURL(path.join(ui, name)).href);
