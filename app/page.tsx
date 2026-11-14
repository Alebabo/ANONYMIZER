"use client";

import { useMemo, useRef, useState } from "react";
import { FileText, Fingerprint, LockKeyhole, Plus, Search, Shield, ShieldCheck, Upload } from "lucide-react";

type Level = "CRITICAL" | "GREY" | "UNCRITICAL";
type Finding = { id: string; value: string; category: string; level: Level; reason: string };
type Doc = { id: string; name: string; type: string; size: string; date: string; findings: Finding[] };
type Tab = "Overview" | "Documents" | "Privacy rules";

const initial: Doc[] = [{
  id: "demo-1", name: "Mandatsvertrag_Muster.pdf", type: "PDF", size: "284 KB", date: "Sample",
  findings: [
    { id: "f1", value: "Max Mustermann", category: "Person", level: "GREY", reason: "Directly identifying information" },
    { id: "f2", value: "IBAN", category: "Bank details", level: "CRITICAL", reason: "Financial information" },
    { id: "f3", value: "§ 280 BGB", category: "Legal reference", level: "UNCRITICAL", reason: "Public legal information" }
  ]
}];

export default function Home() {
  const [tab, setTab] = useState<Tab>("Overview");
  const [docs, setDocs] = useState<Doc[]>(initial);
  const [active, setActive] = useState("demo-1");
  const [search, setSearch] = useState("");
  const [text, setText] = useState("");
  const [notice, setNotice] = useState("Demo mode — files are not uploaded or processed.");
  const input = useRef<HTMLInputElement>(null);
  const doc = docs.find(d => d.id === active);
  const findings = docs.flatMap(d => d.findings);
  const counts = useMemo(() => ({
    CRITICAL: findings.filter(f => f.level === "CRITICAL").length,
    GREY: findings.filter(f => f.level === "GREY").length,
    UNCRITICAL: findings.filter(f => f.level === "UNCRITICAL").length
  }), [findings]);
  const visible = docs.filter(d => d.name.toLowerCase().includes(search.toLowerCase()));

  function addFiles(files: FileList | null) {
    if (!files?.length) return;
    const added = Array.from(files).map((f, i) => ({
      id: String(Date.now() + i), name: f.name, type: f.name.split(".").pop()?.toUpperCase() || "FILE",
      size: Math.max(1, Math.round(f.size / 1024)) + " KB", date: "Just now", findings: []
    }));
    setDocs(v => [...added, ...v]); setActive(added[0].id); setTab("Documents");
    setNotice("Filename added locally. File contents are not uploaded or processed.");
  }

  function addText() {
    if (!text.trim()) return;
    const d = { id: String(Date.now()), name: "Text note " + (docs.length + 1) + ".txt", type: "TXT", size: text.length + " chars", date: "Just now", findings: [] };
    setDocs(v => [d, ...v]); setActive(d.id); setText("");
    setNotice("Text is only stored in temporary browser state.");
  }

  return (
    <main className="simple-app">
      <header className="simple-header">
        <a className="simple-brand"><span><Shield size={16}/></span>CATO</a>
        <div className="simple-env"><i/> DEMO ENVIRONMENT</div>
      </header>
      <div className="simple-content">
        <div className="simple-title"><div><p>PRIVACY WORKSPACE</p><h1>Overview</h1></div><button className="button button-dark" onClick={() => input.current?.click()}><Plus size={15}/> Add document</button></div>
        <nav className="subtabs" aria-label="Workspace sections">
          {(["Overview", "Documents", "Privacy rules"] as Tab[]).map(t => <button key={t} className={tab === t ? "subtab active" : "subtab"} onClick={() => setTab(t)}>{t}{t === "Documents" && <span>{docs.length}</span>}</button>)}
        </nav>
        <div className="simple-notice"><LockKeyhole size={14}/><span><b>Prototype only.</b> No real detection, redaction or secure processing is active.</span></div>

        {tab === "Overview" && <>
          <div className="simple-stats">
            <div><span>CRITICAL</span><b>{counts.CRITICAL.toString().padStart(2, "0")}</b><small>Never shared</small></div>
            <div><span>GREY</span><b>{counts.GREY.toString().padStart(2, "0")}</b><small>Consent required</small></div>
            <div><span>UNCRITICAL</span><b>{counts.UNCRITICAL.toString().padStart(2, "0")}</b><small>Allowed by policy</small></div>
          </div>
          <section className="simple-card">
            <div className="simple-card-head"><div><h2>Recent documents</h2><p>Your latest files and text snippets.</p></div><button className="text-button" onClick={() => setTab("Documents")}>View all →</button></div>
            {docs.slice(0, 4).map(d => <button className="simple-doc-row" key={d.id} onClick={() => { setActive(d.id); setTab("Documents"); }}><FileText size={17}/><b>{d.name}</b><small>{d.date}</small><span>{d.findings.length ? "Analysed" : "Pending"}</span></button>)}
          </section>
          <section className="simple-card policy-summary"><div className="simple-card-head"><div><h2>Privacy policy</h2><p>How Cato treats sensitive information.</p></div><ShieldCheck size={18}/></div><div className="policy-line"><b>Critical</b><span>Always blocked</span></div><div className="policy-line"><b>Grey</b><span>Requires explicit consent</span></div><div className="policy-line"><b>Uncritical</b><span>Allowed by policy</span></div></section>
        </>}

        {tab === "Documents" && <div className="simple-documents">
          <section className="simple-card">
            <div className="simple-card-head"><div><h2>Add content</h2><p>Upload a file or paste legal text.</p></div></div>
            <button className="simple-upload" onClick={() => input.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); addFiles(e.dataTransfer.files); }}><Upload size={19}/><b>Choose a file or drag it here</b><small>PDF, DOCX, TXT</small></button>
            <input ref={input} hidden type="file" multiple accept=".pdf,.docx,.txt" onChange={e => addFiles(e.target.files)}/>
            <textarea value={text} onChange={e => setText(e.target.value)} placeholder="Or paste text here…" rows={3}/>
            <div className="simple-form-foot"><small>Temporary browser state only</small><button className="button button-dark" onClick={addText} disabled={!text.trim()}><Plus size={14}/> Add text</button></div>
          </section>
          <section className="simple-card">
            <div className="simple-card-head"><div><h2>All documents</h2><p>{docs.length} documents in this workspace.</p></div><label className="simple-search"><Search size={14}/><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search"/></label></div>
            {visible.map(d => <button className={"simple-doc-row " + (active === d.id ? "chosen" : "")} key={d.id} onClick={() => setActive(d.id)}><FileText size={17}/><b>{d.name}</b><small>{d.size}</small><span>{d.findings.length ? "Analysed" : "Pending"}</span></button>)}
            {!visible.length && <p className="simple-empty">No documents found.</p>}
          </section>
          {doc && <section className="simple-card"><div className="simple-card-head"><div><h2>Privacy analysis</h2><p>{doc.name}</p></div><Fingerprint size={18}/></div>
            {doc.findings.length ? doc.findings.map(f => <div className="simple-finding" key={f.id}><div><b>{f.level}</b><small>{f.category}</small></div><strong>{f.value}</strong><p>{f.reason}</p>{f.level === "CRITICAL" && <small>Always blocked</small>}</div>) : <p className="simple-empty">No analysis available. The processing engine is not connected yet.</p>}
          </section>}
        </div>}

        {tab === "Privacy rules" && <section className="simple-card rules-card"><div className="simple-card-head"><div><h2>Privacy rules</h2><p>Default handling for detected information.</p></div></div><div className="policy-line"><b>Critical</b><span>Never shared with an AI agent. Consent cannot override this rule.</span></div><div className="policy-line"><b>Grey</b><span>Shared only after explicit, request-specific consent.</span></div><div className="policy-line"><b>Uncritical</b><span>May be shared according to the active policy.</span></div><p className="rules-footnote">Policy enforcement is a planned feature and is not active in this prototype.</p></section>}

        <footer className="simple-footer"><span>© 2026 CATO</span><span>{notice}</span></footer>
      </div>
    </main>
  );
}
