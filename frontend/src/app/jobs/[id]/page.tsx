import JobView, { type Tab } from "@/components/JobView";

const TABS: Tab[] = ["progress", "agents", "quality", "cast", "read", "edit"];

export default async function JobPage(props: PageProps<"/jobs/[id]">) {
  const { id } = await props.params;
  // ?tab=quality opens the Agent timeline on the Editor's quality loop (handy for demos).
  const { tab } = await props.searchParams;
  const initial = TABS.find((t) => t === tab);
  return <JobView id={id} initialTab={initial} />;
}
