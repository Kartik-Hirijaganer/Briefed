/** Header Lambda Function URL OAC requires for body-bearing SigV4 requests. */
export const AWS_PAYLOAD_HASH_HEADER = 'x-amz-content-sha256';

const PAYLOAD_HASH_METHODS = new Set(['POST', 'PUT', 'PATCH']);

/**
 * Return whether a request method must send a SigV4 payload hash.
 *
 * @param method - HTTP method from a `Request` or fetch init object.
 * @returns `true` for methods whose Lambda Function URL requests may carry bodies.
 */
export function shouldAttachPayloadHash(method: string): boolean {
  return PAYLOAD_HASH_METHODS.has(method.toUpperCase());
}

/**
 * Compute the lowercase hex SHA-256 digest of the exact payload bytes.
 *
 * @param payload - Bytes that will be sent as the request body.
 * @returns Lowercase hexadecimal SHA-256 digest.
 * @throws Error when the Web Crypto API is unavailable.
 */
export async function computePayloadSha256Hex(payload: ArrayBuffer | Uint8Array): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error('Web Crypto API is required to compute SigV4 payload hashes.');
  }

  const bytes = payload instanceof Uint8Array ? payload : new Uint8Array(payload);
  const nodeBuffer = (globalThis as { Buffer?: { from(payload: Uint8Array): Uint8Array } }).Buffer;
  const digestPayload = (nodeBuffer ? nodeBuffer.from(bytes) : bytes) as BufferSource;
  const digest = await globalThis.crypto.subtle.digest('SHA-256', digestPayload);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}
