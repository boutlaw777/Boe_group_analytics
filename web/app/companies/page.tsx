import { redirect } from "next/navigation";

// /companies is the API's path for the coverage list; the human-facing page
// is the dashboard. Redirect so pasted/guessed URLs land somewhere useful.
export default function CompaniesRedirect() {
  redirect("/dashboard");
}
