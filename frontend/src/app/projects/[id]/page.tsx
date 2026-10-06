import SeriesView from "@/components/SeriesView";

export default async function SeriesPage(props: PageProps<"/projects/[id]">) {
  const { id } = await props.params;
  return <SeriesView id={id} />;
}
