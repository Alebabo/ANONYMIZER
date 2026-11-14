"use client";

import { useMemo, useRef, useState } from "react";
import {
  ArrowUpRight, Check, ChevronDown, FileText, Fingerprint, FolderOpen,
  LockKeyhole, MoreHorizontal, Plus, Search, Shield, ShieldAlert,
  ShieldCheck, Upload, X
} from "lucide-react";

type Level = "CRITICAL" | "GREY" | "UNCRITICAL";
type Finding = { id: string; value: string; category: string; level: Level; reason: string };
type Doc = { id: string; name: string; type: string; size: string; date: string; findings: Finding[] };

const initial: Doc[] = [{
  id: "demo-1", name: "Mandatsvertrag_Muster.pdf", type: "PDF", size: "284 KB", date: "Beispiel",
  findings: [
    { id: "f1", value: "Max Mustermann", category: "Person", level: "GREY", reason: "Direkt identifizierende Angabe" },
    { id: "f2", value: "IBAN", category: "Bankverbindung", level: "CRITICAL", reason: "Finanzielle Information" },
    { id: "f3", value: "§ 280 BGB", category: "Rechtsnorm", level: "UNCRITICAL", reason: "Öffentliche Rechtsinformation" }
  ]
}];

const levelMeta: Record<Level, { label: string; hint: string }> = {
  CRITICAL: { label: "Critical", hint: "Wird niemals geteilt" },
  GREY: { label: "Grey", hint: "Explizite Freigabe nötig" },
  UNCRITICAL: { label: "Uncritical", hint: "Gemäß Policy erlaubt" }
};

export default function Home() {
  const [docs, setDocs] = useState<Doc[]>(initial);
  const [active, setActive] = useState("demo-1");
  const [search, setSearch] = useState("");
  const [text, setText] = useState("");
  const [consents, setConsents] = useState<string[]>([]);
  const [notice, setNotice] = useState("Demo-Modus · Es findet keine echte Analyse statt.");
  const input = useRef<HTMLInputElement>(null);
  const doc = docs.find(d => d.id === active);
  const findings = docs.flatMap(d => d.findings);
  const counts = useMemo(() => ({
    CRITICAL: findings.filter(f => f.level === "CRITICAL").length,
    GREY: findings.filter(f => f.level === "GREY").length,
    UNCRITICAL: findings.filter(f => f.level === "UNCRITICAL").length
  }), [findings]);
  const visible = docs.filter(d => d.name.toLowerCase().includes(search.toLowerCase()));

  function addFiles(list: FileList | null) {
    if (!list?.length) return;
    const added = Array.from(list).map((f, i) => ({
      id: String(Date.now() + i), name: f.name, type: f.name.split(".").pop()?.toUpperCase() || "FILE",
      size: Math.max(1, Math.round(f.size / 1024)) + " KB", date: "Gerade eben", findings: []
    }));
    setDocs(v => [...added, ...v]);
    setActive(added[0].id);
    setNotice("Dateiname lokal erfasst. Dateiinhalt wird nicht hochgeladen oder verarbeitet.");
  }

  function addText() {
    if (!text.trim()) return;
    const d = { id: String(Date.now()), name: "Textnotiz_" + (docs.length + 1) + ".txt", type: "TXT", size: text.length + " Zeichen", date: "Gerade eben", findings: [] };
    setDocs(v => [d, ...v]);
    setActive(d.id);
    setText("");
    setNotice("Text lokal im Browser erfasst. Es wurde keine Klassifizierung durchgeführt.");
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#"><span className="brand-mark"><Shield size={17} strokeWidth={2.4} /></span><span>CATO</span></a>
        <div className="workspace-label">WORKSPACE</div>
        <button className="nav-item active"><FolderOpen size={16} /> Documents <span className="nav-count">{docs.length}</span></button>
        <button className="nav-item" onClick={() => setNotice("Die Privacy-Policy-Verwaltung ist noch nicht implementiert.")}><ShieldCheck size={16} /> Privacy policies</button>
        <div className="sidebar-bottom">
          <div className="secure-card"><div className="secure-icon"><LockKeyhole size={15}/></div><b>Privacy first.</b><p>Deine Daten bleiben unter deiner Kontrolle.</p><span><i/> LOCAL DEMO</span></div>
          <div className="profile"><div className="avatar">AB</div><div><b>Workspace</b><small>Personal account</small></div><MoreHorizontal size={17}/></div>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><span className="slash">/</span><b>Documents</b></div>
          <div className="top-actions"><span className="demo-pill"><i/> Demo environment</span><button className="icon-button" aria-label="Mehr Optionen"><MoreHorizontal size={18}/></button></div>
        </header>

        <div className="content">
          <div className="page-heading">
            <div><div className="overline">PRIVACY WORKSPACE</div><h1>Documents</h1><p>Manage sensitive information before it reaches your AI agents.</p></div>
            <button className="button button-dark" onClick={() => input.current?.click()}><Plus size={16}/> Add document</button>
          </div>

          <div className="notice"><ShieldAlert size={16}/><span><b>Prototype mode.</b> Files and text are only held in temporary browser state. No real detection, redaction or secure processing is active.</span><button onClick={() => setNotice("Demo-Modus · Es findet keine echte Analyse statt.")} aria-label="Hinweis schließen"><X size={15}/></button></div>

          <div className="metrics">
            {(["CRITICAL", "GREY", "UNCRITICAL"] as Level[]).map(level => (
              <div className="metric-card" key={level}>
                <div className="metric-top"><span className={"level-dot " + level.toLowerCase()}/><span>{levelMeta[level].label}</span><span className="metric-context">{levelMeta[level].hint}</span></div>
                <div className="metric-number">{counts[level].toString().padStart(2, "0")}</div>
              </div>
            ))}
          </div>

          <div className="workspace-grid">
            <div className="left-column">
              <section className="card">
                <div className="card-heading"><div><h2>Add content</h2><p>Upload a document or paste text to get started.</p></div><span className="step-label">01 / INPUT</span></div>
                <button className="upload-zone" onClick={() => input.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); addFiles(e.dataTransfer.files); }}>
                  <span className="upload-icon"><Upload size={18}/></span><b>Click to upload <span>or drag and drop</span></b><small>PDF, DOCX or TXT · up to 20 MB</small>
                </button>
                <input ref={input} hidden type="file" multiple accept=".pdf,.docx,.txt" onChange={e => addFiles(e.target.files)}/>
                <div className="separator"><span/>OR PASTE TEXT<span/></div>
                <textarea value={text} onChange={e => setText(e.target.value)} placeholder="Paste legal text here..." rows={4}/>
                <div className="card-footer"><span><LockKeyhole size={12}/> Temporary browser state only</span><button className="button button-outline" onClick={addText} disabled={!text.trim()}><Plus size={14}/> Add text</button></div>
              </section>

              <section className="card library-card">
                <div className="card-heading"><div><h2>Library <span className="count-badge">{docs.length}</span></h2><p>Your uploaded documents and text snippets.</p></div>
                  <label className="search-box"><Search size={15}/><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search documents"/></label>
                </div>
                <div className="table-head"><span>NAME</span><span>TYPE</span><span>SIZE</span><span>STATUS</span><span/></div>
                {visible.map(d => <button key={d.id} className={"document-row " + (active === d.id ? "selected" : "")} onClick={() => setActive(d.id)}>
                  <span className="file-name"><span className="file-icon"><FileText size={17}/></span><span><b>{d.name}</b><small>{d.date}</small></span></span>
                  <span className="file-type">{d.type}</span><span className="file-size">{d.size}</span><span><span className={"status " + (d.findings.length ? "analysed" : "pending")}>{d.findings.length ? "Analysed" : "Pending"}</span></span><ChevronDown className="row-chevron" size={15}/>
                </button>)}
                {!visible.length && <div className="empty-state">No documents found.</div>}
              </section>
            </div>

            <aside className="card analysis-card">
              <div className="card-heading"><div><h2>Privacy analysis</h2><p>Information detected in this document.</p></div><span className="analysis-icon"><Fingerprint size={17}/></span></div>
              {doc ? <>
                <div className="active-document"><FileText size={15}/><b>{doc.name}</b></div>
                {doc.findings.length ? doc.findings.map(f => <div className="finding" key={f.id}>
                  <div className="finding-head"><span className={"level-tag " + f.level.toLowerCase()}>{levelMeta[f.level].label}</span><span>{f.category}</span></div>
                  <b className="finding-value">{f.value}</b><p>{f.reason}</p>
                  {f.level === "GREY" && <label className="consent-row"><input type="checkbox" checked={consents.includes(f.id)} onChange={() => setConsents(v => v.includes(f.id) ? v.filter(x => x !== f.id) : [...v, f.id])}/><span>Allow for this request</span></label>}
                  {f.level === "CRITICAL" && <div className="blocked-row"><LockKeyhole size={13}/> Always blocked</div>}
                  {f.level === "UNCRITICAL" && <div className="allowed-row"><Check size={13}/> Allowed by policy</div>}
                </div>) : <div className="empty-analysis"><Fingerprint size={24}/><b>No analysis available</b><span>Processing engine is not connected yet.</span></div>}
                <div className="policy-note"><ShieldCheck size={16}/><span><b>Policy enforcement</b><br/>Critical data is always blocked. Grey data requires explicit, request-specific consent.</span></div>
              </> : <div className="empty-analysis">Select a document to inspect.</div>}
              <button className="button button-dark full-button" onClick={() => setNotice("Die sichere Freigabe an einen AI Agent ist noch nicht implementiert.")} disabled={!doc?.findings.length}>Review sharing <ArrowUpRight size={15}/></button>
            </aside>
          </div>
          <footer className="footer"><span>© 2026 CATO</span><span>{notice}</span><span>BUILT FOR PRIVACY</span></footer>
        </div>
      </section>
    </main>
  );
}
