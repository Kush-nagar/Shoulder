export default function PlayerLoading() {
  return (
    <div
      role="status"
      aria-label="Loading your clips"
      className="space-y-8"
      aria-busy="true"
    >
      <div className="h-9 w-40 rounded-lg bg-surface-subtle" />
      <div className="h-24 rounded-xl bg-surface-subtle" />
      <div className="h-28 rounded-xl bg-surface-subtle" />
    </div>
  );
}
