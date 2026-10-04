import JobView from "@/components/JobView";

export default async function JobPage(props: PageProps<"/jobs/[id]">) {
  const { id } = await props.params;
  return <JobView id={id} />;
}
