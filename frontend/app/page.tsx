import { redirect } from "next/navigation";
import ProductLanding from "./_components/ProductLanding";

type HomePageProps = {
  searchParams: Promise<{ invitation?: string | string[] }>;
};

export default async function HomePage({ searchParams }: HomePageProps) {
  const params = await searchParams;
  const invitation = Array.isArray(params.invitation)
    ? params.invitation[0]
    : params.invitation;

  if (invitation) {
    redirect(`/auth?invitation=${encodeURIComponent(invitation)}`);
  }

  return <ProductLanding />;
}
