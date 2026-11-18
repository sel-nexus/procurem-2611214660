import RecordDetail from '../../../components/RecordDetail';
/** Open the requested record. */
export default async function Page({ params }: { params: Promise<{ resource: string; id: string }> }) { const { resource, id } = await params; return <RecordDetail resource={resource} id={id} />; }
