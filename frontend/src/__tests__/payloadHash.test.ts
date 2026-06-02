import { describe, expect, it } from 'vitest';

import { computePayloadSha256Hex, shouldAttachPayloadHash } from '../api/payloadHash';

describe('payloadHash', () => {
  it('computes the SHA-256 hash for exact UTF-8 payload bytes', async () => {
    const encoder = new TextEncoder();

    await expect(computePayloadSha256Hex(encoder.encode(''))).resolves.toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    );
    await expect(computePayloadSha256Hex(encoder.encode('{}'))).resolves.toBe(
      '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a',
    );
  });

  it('limits payload hashes to methods that can carry OAC-signed bodies', () => {
    expect(shouldAttachPayloadHash('POST')).toBe(true);
    expect(shouldAttachPayloadHash('patch')).toBe(true);
    expect(shouldAttachPayloadHash('GET')).toBe(false);
    expect(shouldAttachPayloadHash('DELETE')).toBe(false);
  });
});
