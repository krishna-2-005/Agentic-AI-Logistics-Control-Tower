/**
 * Names and addresses used by the browser title, the header, the footer and the
 * social-card metadata, so they cannot drift apart (D-090: one project name, the full one).
 */

export const PROJECT_NAME = "Agentic AI Logistics Control Tower";

export const SITE_URL = "https://control-tower-mu-rouge.vercel.app";

export const SITE_DESCRIPTION =
  "A corridor-level audit of where road-freight time estimates are systematically wrong, across 26,369 real legs, with a measured agent layer built on top of it.";

/** A per-page description, so each page has its own search and social snippet. */
export function pageMeta(title: string, description: string) {
  return {
    title,
    description,
    openGraph: {
      title: `${title} · ${PROJECT_NAME}`,
      description,
      images: [{ url: "/og.png", width: 1200, height: 630, alt: PROJECT_NAME }],
    },
  };
}
