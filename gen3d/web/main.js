// Entry point: import every module (each registers its hooks on S), then boot.
// A plain static graph: a top-level `await import()` inside app.js would deadlock on the cycle.
import { boot } from "./app.js";
import "./composer.js";
import "./cards.js";

boot();
