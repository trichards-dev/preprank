"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && (!user || !user.is_admin)) {
      router.replace("/");
    }
  }, [user, loading, router]);

  if (loading) return <div className="p-8 text-steel-gray">Loading…</div>;
  if (!user?.is_admin) return null;

  return <>{children}</>;
}
