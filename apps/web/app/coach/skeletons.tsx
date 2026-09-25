import { Bone, keys, Loading } from "../../components/skeleton";

/** The coach page header bar: title left, "Upload match" right. */
export function CoachHead({ title = "w-40" }: { title?: string }) {
  return (
    <div className="flex items-center justify-between gap-6 border-b border-line px-5 py-4 md:px-6 lg:min-h-16 lg:px-8">
      <Bone className={`h-9 ${title}`} />
      <Bone className="h-10 w-32" />
    </div>
  );
}

export function CoachRows({ count = 5 }: { count?: number }) {
  return (
    <ul className="divide-y divide-line rounded-xl border border-line">
      {keys(count).map((key) => (
        <li key={key} className="flex items-center gap-3 px-4 py-3.5">
          <Bone className="size-8 rounded-full" />
          <div className="flex-1">
            <Bone className="h-5 w-2/5 max-w-60" />
            <Bone className="mt-1.5 h-4 w-1/4 max-w-40" />
          </div>
        </li>
      ))}
    </ul>
  );
}

export { Bone, Loading };
