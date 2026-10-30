"use client";

import { BellIcon, ShieldAlertIcon } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { RoleNote } from "@/components/role-note";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCurrentProject } from "@/features/projects/api";
import { useTabParam } from "@/lib/use-tab-param";

import { ChannelsSection } from "./channels-section";
import { RulesSection } from "./rules-section";

const TABS = ["rules", "channels"] as const;

export function AlertsScreen() {
  const { pid, canEdit, project } = useCurrentProject();
  const [tab, setTab] = useTabParam("rules", TABS);
  return (
    <>
      <PageHeader
        title="Alerts"
        description="Rules decide what counts as a problem; channels decide who hears about it. A problem notifies once and resolves itself when a later scan no longer shows it."
      />
      {project && !canEdit && <RoleNote className="mb-4">You are a viewer in {project.name}: you can see the alert setup. Editors and owners change it.</RoleNote>}
      <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
        <TabsList>
          <TabsTrigger value="rules">
            <ShieldAlertIcon />
            Rules
          </TabsTrigger>
          <TabsTrigger value="channels">
            <BellIcon />
            Channels
          </TabsTrigger>
        </TabsList>
        <TabsContent value="rules">
          <RulesSection pid={pid} canEdit={canEdit} />
        </TabsContent>
        <TabsContent value="channels">
          <ChannelsSection pid={pid} canEdit={canEdit} />
        </TabsContent>
      </Tabs>
    </>
  );
}
