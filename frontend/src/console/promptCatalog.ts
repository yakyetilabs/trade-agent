import type { GoodsCategory, Vendor } from "../types/api";

// One real, requirement-heavy HTS code per goods category, so the tariff prompt always
// references data the seed KB actually holds. Source of truth for the seed is
// backend/src/data/generators.py - update together if the seed changes.
const HTS_BY_CATEGORY: Record<GoodsCategory, string> = {
  electronics: "8542.31.0001", // microprocessors - import/end-use license
  textiles: "6203.42.4011", // men's cotton trousers - visa + quota verification
  agriculture: "0207.14.0000", // frozen chicken cuts - FSIS import license
  machinery: "8456.11.1000", // laser machining centers - dual-use license
  pharmaceuticals: "3004.90.9228", // dosage-form medicaments - FDA admissibility
  chemicals: "2811.19.6090", // inorganic acids - import license/permit + TSCA
};

export interface ExamplePrompt {
  label: string;
  prompt: string;
}

/**
 * The curated five-prompt tour, grounded in the selected vendor's seed data: the full
 * grounded pipeline, a category-specific tariff lookup, both deterministic pre-model
 * guards, and the no-shipment Approve gate.
 */
export function buildExamplePrompts(vendor: Vendor, vendors: Vendor[]): ExamplePrompt[] {
  const htsCode = vendor.categories.map((category) => HTS_BY_CATEGORY[category]).find(Boolean);
  const otherVendor = vendors.find((v) => v.vendor_id !== vendor.vendor_id);

  const prompts: ExamplePrompt[] = [
    {
      // ID-agnostic on purpose: shipment ids are seed-RNG-generated, so the agent finds
      // the vendor's held shipments itself rather than trusting a hardcoded id.
      label: "Held shipment",
      prompt: "Why is my flagged shipment held, and what is required to clear it?",
    },
    {
      label: "Tariff & licensing",
      prompt: htsCode
        ? `What are the import and licensing requirements for HTS ${htsCode}?`
        : "What tariff and licensing rules apply to my latest shipment's goods?",
    },
    {
      // Spaced "under the table" matches the escalation guard's deterministic pattern;
      // the guard also normalizes hyphens server-side, but the chip stays exact.
      label: "Escalation guard",
      prompt:
        "A broker offered to pay the inspector under the table to speed up clearance. Is that allowed?",
    },
    {
      // S-9999 does not exist in the seed (ids are sequential from S-1001), so the
      // lookup returns zero shipments and the Approve action gates off.
      label: "No matching shipment",
      prompt: "What is the status of shipment S-9999?",
    },
  ];

  if (otherVendor) {
    prompts.push({
      // The cross-vendor guard keys on vendor IDs (V-###), so the prompt must name the
      // id; the legal name rides along for the human reading it.
      label: "Scope guard",
      prompt: `Show me the held shipments for ${otherVendor.vendor_id} (${otherVendor.legal_name}).`,
    });
  }
  return prompts;
}
