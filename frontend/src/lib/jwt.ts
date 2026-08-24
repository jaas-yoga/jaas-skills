/** Reads the `exp` claim (as epoch milliseconds) out of an already-trusted
 * JWT — no signature verification here, because this only ever runs on a
 * token our own backend (ui-design.md §4.3) just handed back to us over a
 * server-to-server call. Never use this to validate a token from elsewhere. */
export function decodeJwtExpMs(jwt: string): number | null {
  const payloadSegment = jwt.split(".")[1];
  if (!payloadSegment) return null;
  try {
    const base64 = payloadSegment.replace(/-/g, "+").replace(/_/g, "/");
    const json = Buffer.from(base64, "base64").toString("utf-8");
    const exp = JSON.parse(json)?.exp;
    return typeof exp === "number" ? exp * 1000 : null;
  } catch {
    return null;
  }
}
