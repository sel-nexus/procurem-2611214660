import RecordDetail from '../../../components/RecordDetail';
import RequisitionForm from '../../../components/RequisitionForm';
import ApprovalDetail from '../../../components/ApprovalDetail';
/** Open the requested record. */
export default async function Page({ params }: { params: Promise<{ resource: string; id: string }> }) { const { resource, id } = await params; return resource === 'requisitions' && id === 'new' ? <RequisitionForm /> : resource === 'approvals' ? <ApprovalDetail id={id} /> : <RecordDetail resource={resource} id={id} />; }
