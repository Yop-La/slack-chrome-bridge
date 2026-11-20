// Validation of the parameters sent by the command line. Kept in its own module so it can be
// unit-tested with Node without a browser.

const ID = /^[A-Z0-9]{8,14}$/;
const TS = /^\d{10}\.\d{6}$/;
const FILE_ID = /^F[A-Z0-9]{8,14}$/;

const int = (v, lo, hi) => v === undefined || (Number.isInteger(v) && v >= lo && v <= hi);
const cursorOk = (c) => c === undefined || (typeof c === 'string' && c.length <= 500);

export function validate(op, p) {
  if (!p || typeof p !== 'object' || Array.isArray(p)) return false;
  if (!cursorOk(p.cursor)) return false;
  switch (op) {
    case 'search':
      return typeof p.query === 'string' && p.query.trim().length > 0 && p.query.length <= 500
        && int(p.count, 1, 100) && int(p.page, 1, 100)
        && [undefined, 'score', 'timestamp'].includes(p.sort)
        && [undefined, 'asc', 'desc'].includes(p.sort_dir);
    case 'thread':
      return ID.test(p.channel ?? '') && TS.test(p.ts ?? '') && int(p.limit, 1, 1000);
    case 'history':
      return ID.test(p.channel ?? '') && int(p.limit, 1, 1000)
        && [p.oldest, p.latest].every((t) => t === undefined || TS.test(t) || /^\d{10}$/.test(t));
    case 'channel':
      return ID.test(p.channel ?? '');
    case 'user':
      return ID.test(p.user ?? '');
    case 'file':
      return FILE_ID.test(p.file ?? '');
    default:
      return false;
  }
}
