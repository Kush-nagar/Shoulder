export default function PracticeLoading() {
  return (
    <div role="status" aria-label="Loading practice" aria-busy="true">
      <div className="h-9 w-36 rounded-lg bg-surface-subtle" />
      <div className="mt-4 h-12 max-w-[48ch] rounded-lg bg-surface-subtle" />
      <div className="mt-8 space-y-3">
        <div className="h-16 rounded-lg bg-surface-subtle" />
        <div className="h-16 rounded-lg bg-surface-subtle" />
        <div className="h-16 rounded-lg bg-surface-subtle" />
      </div>
    </div>
  );
}
