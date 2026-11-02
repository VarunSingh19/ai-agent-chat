/**
 * Local-only chat token issuer for the Vite dev server (Architecture.md §6.9).
 *
 * Publishes `GET /dev/jwks.json` and mints 15-minute tenant tokens at `GET /dev/token`.
 * Runs only under `vite serve`, answers loopback requests only, and is never part of the
 * built bundle. The key and the dev identity persist in the git-ignored `widget/.dev/`
 * so the backend's cached JWKS and the user's thread survive dev-server restarts.
 */
import { createPublicKey, createSign, generateKeyPairSync, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Plugin } from 'vite';

/** Must match PDAGENT_TOKEN_ISSUER in the local `.env`. */
export const DEV_ISSUER = 'http://127.0.0.1:5173/dev';
const AUDIENCE = 'pdagent';
const TOKEN_TTL_S = 15 * 60;

interface DevIdentity {
  kid: string;
  privateKeyPem: string;
  orgId: string;
  userId: string;
  propertyId: string;
  unitId: string;
}

function loadOrCreateIdentity(stateDir: string): DevIdentity {
  const file = join(stateDir, 'identity.json');
  if (existsSync(file)) {
    return JSON.parse(readFileSync(file, 'utf8')) as DevIdentity;
  }
  const { privateKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
  const identity: DevIdentity = {
    kid: `dev-${randomUUID()}`,
    privateKeyPem: privateKey.export({ type: 'pkcs8', format: 'pem' }).toString(),
    orgId: randomUUID(),
    userId: randomUUID(),
    propertyId: randomUUID(),
    unitId: randomUUID(),
  };
  mkdirSync(stateDir, { recursive: true });
  writeFileSync(file, JSON.stringify(identity, null, 2), { mode: 0o600 });
  return identity;
}

function base64url(input: string | Buffer): string {
  return Buffer.from(input).toString('base64url');
}

function mintToken(identity: DevIdentity): string {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: 'RS256', typ: 'JWT', kid: identity.kid };
  const payload = {
    sub: identity.userId,
    org_id: identity.orgId,
    role: 'tenant',
    property_ids: [identity.propertyId],
    unit_id: identity.unitId,
    jti: randomUUID(),
    iss: DEV_ISSUER,
    aud: AUDIENCE,
    iat: now,
    exp: now + TOKEN_TTL_S,
  };
  const signingInput = `${base64url(JSON.stringify(header))}.${base64url(JSON.stringify(payload))}`;
  const signature = createSign('RSA-SHA256').update(signingInput).sign(identity.privateKeyPem);
  return `${signingInput}.${base64url(signature)}`;
}

function isLoopback(address: string | undefined): boolean {
  return address === '127.0.0.1' || address === '::1' || address === '::ffff:127.0.0.1';
}

export function devIssuer(stateDir: string): Plugin {
  return {
    name: 'pdagent-dev-issuer',
    apply: 'serve',
    configureServer(server) {
      const identity = loadOrCreateIdentity(stateDir);
      const jwk = {
        ...createPublicKey(identity.privateKeyPem).export({ format: 'jwk' }),
        kid: identity.kid,
        alg: 'RS256',
        use: 'sig',
      };
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? '').split('?')[0];
        if (path !== '/dev/jwks.json' && path !== '/dev/token') {
          next();
          return;
        }
        if (!isLoopback(req.socket.remoteAddress)) {
          res.statusCode = 403;
          res.end();
          return;
        }
        res.setHeader('Content-Type', 'application/json');
        res.setHeader('Cache-Control', 'no-store');
        res.end(
          JSON.stringify(path === '/dev/jwks.json' ? { keys: [jwk] } : { token: mintToken(identity) }),
        );
      });
    },
  };
}
