import { ShoulderMark, ShoulderWordmark } from "../components/brand";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-[680px] flex-col justify-center px-5 py-12 md:px-8">
      <header className="mb-12">
        <ShoulderWordmark className="h-auto w-44" />
      </header>
      <h1 className="text-[26px] leading-[1.15] font-semibold md:text-[30px]">
        A quiet space for development.
      </h1>
      <p className="mt-4 text-base leading-relaxed text-muted">
        Shoulder brings a coach’s observations closer to the player.
      </p>
      <footer className="mt-12 flex items-center gap-3 border-t border-line pt-6">
        <ShoulderMark className="size-6" />
        <p className="text-sm text-muted">Shoulder is running.</p>
      </footer>
    </main>
  );
}
