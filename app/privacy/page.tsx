import { PageHeader, Badge } from "@/components/app-shell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detections } from "@/lib/mock";

export default function Privacy() {
  return (
    <>
      <PageHeader title="Privacy" description="Detections · Example data" />
      <div className="text-muted-foreground flex gap-4 border-b px-6 py-2 text-sm">
        {["Detections", "Entities", "Anonymization", "Policies", "Review Queue"].map((t, i) => <span key={t} className={i === 0 ? "text-foreground font-medium" : ""}>{t}</span>)}
      </div>
      <Table><TableHeader><TableRow>{["Entity", "Category", "Risk", "Confidence", "Action", "Policy", "Timestamp"].map(h => <TableHead key={h}>{h}</TableHead>)}</TableRow></TableHeader>
        <TableBody>{detections.map((d, i) => (
          <TableRow key={i}><TableCell>{d.entity}</TableCell><TableCell>{d.category}</TableCell><TableCell><Badge>{d.risk}</Badge></TableCell>
            <TableCell>{d.confidence.toFixed(1)} %</TableCell><TableCell>{d.action}</TableCell><TableCell>{d.policy}</TableCell><TableCell>{d.time}</TableCell></TableRow>
        ))}</TableBody></Table>
    </>
  );
}
