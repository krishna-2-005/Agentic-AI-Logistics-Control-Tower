import type { Metadata } from "next";

import { ArrowLink, PageHeader } from "@/components/ui";

export const metadata: Metadata = {
  title: "Page not found",
  description: "That page does not exist. The map, the corridors and the results are one click away.",
  robots: { index: false },
};

export default function NotFound() {
  return (
    <>
      <PageHeader
        eyebrow="404"
        title="That page does not exist"
        lede={<>The address may have changed. Everything on this site is reachable from the menu.</>}
      />
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <ArrowLink href="/">Home</ArrowLink>
        <ArrowLink href="/network/">The map</ArrowLink>
        <ArrowLink href="/corridors/">Corridor audit</ArrowLink>
        <ArrowLink href="/evidence/">The results</ArrowLink>
      </div>
    </>
  );
}
