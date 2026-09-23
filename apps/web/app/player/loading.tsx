export default function PlayerLoading() {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="space-y-10"
      aria-busy="true"
    >
      <div className="h-9 w-44 rounded-lg bg-surface-subtle" />
      <div className="h-32 rounded-[14px] bg-surface-subtle" />
      <div className="space-y-4">
        <div className="h-6 w-52 rounded-lg bg-surface-subtle" />
        <div className="h-36 rounded-[14px] bg-surface-subtle" />
      </div>
    </div>
  );
}
