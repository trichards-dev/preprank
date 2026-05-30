export const SPORT_SLUGS: Record<string, string> = {
  football: "Football",
  "boys-basketball": "Boys Basketball",
  "girls-basketball": "Girls Basketball",
  baseball: "Baseball",
  softball: "Softball",
  "boys-soccer": "Boys Soccer",
  "girls-soccer": "Girls Soccer",
  volleyball: "Volleyball",
};

export function sportNameFromSlug(slug: string): string | undefined {
  return SPORT_SLUGS[slug];
}

export function sportSlugFromName(name: string): string {
  const entry = Object.entries(SPORT_SLUGS).find(([, v]) => v === name);
  return entry ? entry[0] : name.toLowerCase().replace(/\s+/g, "-");
}
