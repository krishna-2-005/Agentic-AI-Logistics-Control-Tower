import type { Metadata } from "next";

import { NetworkExplorer } from "@/components/NetworkExplorer";
import { PageHeader } from "@/components/ui";
import { getCorridors } from "@/lib/data";
import { num } from "@/lib/format";
import { pageMeta } from "@/lib/site";

export const metadata: Metadata = pageMeta("Network map", "Every audited corridor drawn on India, coloured by how far it runs over plan.");

export default function NetworkPage() {
  const corridors = getCorridors();
  const located = corridors.data.filter(
    (c) => c.src.lat && c.dst.lat
  ).length;

  return (
    <>
      <PageHeader
        eyebrow="Network"
        title="Where the delays actually are"
        lede={
          <>
            Every one of the {num(corridors.data.length)} audited corridors,
            drawn between the two facilities it connects. Thickness and colour
            say how much more it overruns than the network typically does — and
            the blue arcs are corridors that beat the OSRM estimate.
          </>
        }
      />
      <NetworkExplorer
        corridors={corridors.data}
        located={located}
        legend={
          (corridors as unknown as { legend: unknown }).legend as {
            worse: { upto: number; color: string; label: string; range: string }[];
            better: { upto: number; color: string; label: string; range: string }[];
          }
        }
      />
    </>
  );
}
