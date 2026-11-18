import RecordList from '../../components/RecordList';
/** Open the requested record directory. */
export default async function Page({ params }: { params: Promise<{ resource: string }> }) { const { resource } = await params; return <RecordList resource={resource} />; }
