"use client";
import Link from "next/link";
import { useEffect,useState } from "react";
import { api,ApiError } from "@/lib/api";
import type { ReviewLevel2Response, VendorSubmissionSummary } from "@/lib/types";
import { DocumentProcess } from "./DocumentProcess";
import { ReviewerWorkspace } from "./ReviewerWorkspace";
export function ReviewerLoader({tenderId,tenderTitle,initialStage="level1"}:{tenderId:string;tenderTitle:string;initialStage?:"level1"|"level2"|"level3"}){const[bids,setBids]=useState<VendorSubmissionSummary[]|null>(null);const[saved,setSaved]=useState<ReviewLevel2Response|null>(null);const[error,setError]=useState("");useEffect(()=>{Promise.all([api.submissions(tenderId),api.savedReviewLevel2(tenderId).catch(()=>null)]).then(([items,shortlist])=>{setBids(items);setSaved(shortlist)}).catch(e=>setError(e instanceof ApiError?e.message:"Could not load review"))},[tenderId]);if(error)return <div className="auth-required"><h2>Reviewer access required</h2><p>{error}</p><Link className="btn btn-primary" href="/login">Sign in</Link></div>;if(!bids)return <DocumentProcess label="Opening secure review" detail="Confirming reviewer access and loading the vendor register"/>;return <ReviewerWorkspace tenderId={tenderId} tenderTitle={tenderTitle} initialBids={bids} initialShortlist={saved} initialStage={initialStage}/>}
