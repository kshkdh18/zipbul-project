import type {Metadata} from 'next';
import './globals.css';
export const metadata:Metadata={title:'Zipbul — Field Explorer',description:'Explore captured spaces and inspect hazards with original video evidence'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>;}
