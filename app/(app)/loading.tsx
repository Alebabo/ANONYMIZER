// Shown instantly on navigation while the server renders the next page, so tab switches never feel frozen.
export default function WorkspaceLoading() {
  return (
    <div aria-busy="true" aria-label="Loading" className="animate-pulse">
      <div className="border-b px-4 pt-2 pb-3 md:px-6">
        <div className="bg-muted h-3 w-40 rounded" />
        <div className="bg-muted mt-3 h-5 w-56 rounded" />
      </div>
      <div className="space-y-4 p-4 md:p-6">
        <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map(i => <div key={i} className="bg-muted h-20 rounded-lg" />)}
        </div>
        <div className="bg-muted h-64 rounded-lg" />
      </div>
    </div>
  );
}
