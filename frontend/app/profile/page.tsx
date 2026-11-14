"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, ErrorNote } from "@/components/ui";

type Profile = Awaited<ReturnType<typeof api.me>>;

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.me().then(setProfile).catch((reason) => setError(reason instanceof Error ? reason.message : "Could not load profile."));
  }, []);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!profile) return <p className="text-sm text-[hsl(var(--fg-muted))]">Loading profile…</p>;

  return <div className="space-y-8">
    <div><p className="eyebrow">Account</p><h1 className="font-display mt-2 text-4xl font-medium">Profile</h1><p className="mt-2 text-sm text-[hsl(var(--fg-muted))]">Your identity and workspace access.</p></div>
    <Card className="p-6"><dl className="grid gap-6 sm:grid-cols-2">
      <Detail label="Name" value={profile.full_name || "Not provided"}/>
      <Detail label="Email" value={profile.email}/>
      <Detail label="Organisation" value={profile.organisation || "Not provided"}/>
      <Detail label="Account type" value={profile.role === "reviewer" ? "Company reviewer" : "Vendor"}/>
      <Detail label="Access" value={profile.role === "reviewer" ? "Company evaluation workspace" : "Private vendor bid workspace"}/>
      <Detail label="Account status" value="Active"/>
    </dl></Card>
    <p className="text-xs text-[hsl(var(--fg-subtle))]">Vendor and company accounts are independent. Vendor submissions remain private to their owner; company-review tools require a reviewer account.</p>
  </div>;
}

function Detail({label,value}:{label:string;value:string}) { return <div><dt className="label">{label}</dt><dd className="mt-2 break-words text-sm font-semibold">{value}</dd></div>; }
