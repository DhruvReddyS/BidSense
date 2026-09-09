"use client";
import Link from "next/link";
import { useEffect,useState } from "react";
import { api,ApiError } from "@/lib/api";
import type { GapReportResponse } from "@/lib/types";
import { DocumentProcess } from "./DocumentProcess";
import { LiveGapReport } from "./LiveGapReport";
export function BidReportLoader({tenderId,vendorId}:{tenderId:string;vendorId:string}){const[data,setData]=useState<GapReportResponse|null>(null);const[error,setError]=useState("");useEffect(()=>{api.gapReport(tenderId,vendorId).then(setData).catch(e=>setError(e instanceof ApiError?e.message:"Could not build this report"))},[tenderId,vendorId]);if(error)return <div className="auth-required"><h2>Sign in to view this bid</h2><p>{error}</p><Link className="btn btn-primary" href="/login">Sign in</Link></div>;if(!data)return <DocumentProcess label="Opening your bid review" detail="Confirming ownership before loading confidential evidence"/>;return <><div className="bid-review-heading"><Link href={`/tenders/${encodeURIComponent(tenderId)}`} className="review-back">← Tender workspace</Link><h1 className="review-page-title">Bid review</h1><p className="review-page-subtitle">{data.report.vendor_name??vendorId} · checked against <span className="font-mono text-xs">{tenderId}</span></p></div><LiveGapReport initial={data}/></>}
