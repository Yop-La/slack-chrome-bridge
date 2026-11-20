// Unit tests for the extension's request validation. Run with: node --test tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import { validate } from '../extension/validate.js';

test('search accepts a normal query', () => {
  assert.equal(validate('search', { query: 'deploy in:#ops', count: 20, page: 1, sort: 'timestamp', sort_dir: 'desc' }), true);
});

test('search rejects empty, too long or out-of-range input', () => {
  assert.equal(validate('search', { query: '   ' }), false);
  assert.equal(validate('search', { query: 'x'.repeat(501) }), false);
  assert.equal(validate('search', { query: 'x', count: 500 }), false);
  assert.equal(validate('search', { query: 'x', sort: 'random' }), false);
});

test('thread needs a channel ID and a message ts', () => {
  assert.equal(validate('thread', { channel: 'C0123ABCD', ts: '1731000000.123456' }), true);
  assert.equal(validate('thread', { channel: 'general', ts: '1731000000.123456' }), false);
  assert.equal(validate('thread', { channel: 'C0123ABCD', ts: 'yesterday' }), false);
});

test('history accepts Unix timestamps', () => {
  assert.equal(validate('history', { channel: 'C0123ABCD', oldest: '1730419200', limit: 50 }), true);
  assert.equal(validate('history', { channel: 'C0123ABCD', oldest: '2026-11-01' }), false);
});

test('file needs an F... ID', () => {
  assert.equal(validate('file', { file: 'F0123ABCDEF' }), true);
  assert.equal(validate('file', { file: 'C0123ABCDEF' }), false);
});

test('unknown operations and bad shapes are refused', () => {
  assert.equal(validate('chat.postMessage', { channel: 'C0123ABCD' }), false);
  assert.equal(validate('search', null), false);
  assert.equal(validate('search', ['query']), false);
  assert.equal(validate('search', { query: 'x', cursor: 42 }), false);
});
