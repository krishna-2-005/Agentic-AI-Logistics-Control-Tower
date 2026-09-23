/**
 * Repository constants.
 *
 * Kept apart from `lib/data.ts` on purpose: that module reads the filesystem at
 * build time, so anything importing it is pulled server-side. Client components
 * need the repo URL too, and importing it from `data.ts` would drag `node:fs`
 * into the browser bundle.
 */

export const REPO_URL =
  "https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower";

/** Link straight to a file on GitHub, so "Evidence" is one click, not a path. */
export function repoFileUrl(file: string): string {
  return `${REPO_URL}/blob/main/${file}`;
}
