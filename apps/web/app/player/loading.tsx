export default function PlayerLoading() {
  return (
    <div
      role="status"
      aria-label="Loading"
      aria-busy="true"
      className="mx-auto max-w-[680px] lg:max-w-none"
    >
      <div className="h-10 w-48 rounded-lg bg-surface-subtle md:h-12" />
      <div className="mt-2 h-5 w-40 rounded bg-surface-subtle" />
      <div className="mt-6 grid gap-8 md:mt-8 lg:grid-cols-12 lg:gap-x-6 lg:gap-y-10">
        <div className="h-64 rounded-[14px] bg-surface-subtle lg:col-span-8 lg:h-80" />
        <div className="h-48 rounded-xl bg-surface-subtle lg:col-span-4 lg:h-80" />
        <div className="h-56 rounded-xl bg-surface-subtle lg:col-span-8" />
        <div className="h-56 rounded-xl bg-surface-subtle lg:col-span-4" />
      </div>
    </div>
  );
}
