"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import type { GapReportResponse } from "@/lib/types";
import { GapReport } from "./GapReport";

/**
 * A server-rendered report that can still re-check itself.
 *
 * The standalone report page is a server component, which is right — a vendor
 * links it to whoever holds the missing certificate, and that link should
 * render without waiting on the client. But the staleness re-check has to
 * refetch, so the initial payload is handed to this thin client wrapper rather
 * than making the whole page client-side.
 */
export function LiveGapReport({ initial }: { initial: GapReportResponse }) {
  const [data, setData] = useState(initial);

  return (
    <GapReport
      data={data}
      onRefresh={async (acknowledge) => {
        setData(
          await api.gapReport(
            initial.report.tender_id,
            initial.report.vendor_id,
            acknowledge,
          ),
        );
      }}
    />
  );
}
