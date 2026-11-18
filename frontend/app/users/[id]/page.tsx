import Shell from '../../../components/Shell';
import { UserDetail } from '../../../components/Users';
/** Open an account's editable details. */
export default async function Page({params}:{params:Promise<{id:string}>}) { const {id} = await params; return <Shell title="Users"><UserDetail id={id}/></Shell>; }
