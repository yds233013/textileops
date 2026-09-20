"use client";

import Link from "next/link";
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  Table,
  Td,
} from "@/components/ui";
import { humanise, money, quantity } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { FabricSpec, Material } from "@/lib/types";

export default function MaterialsPage() {
  const materials = useApi<Material[]>("/materials");
  const specs = useApi<FabricSpec[]>("/fabric-specs");

  return (
    <>
      <PageHeader
        title="Materials and fabrics"
        description="The catalogue. A yarn count is not a weight, and GSM is an attribute of a
          fabric — never a quantity."
      />

      <Card title="Fabric specifications" className="mb-4">
        {specs.loading && !specs.data ? (
          <Loading />
        ) : specs.error ? (
          <ErrorState error={specs.error} onRetry={specs.reload} />
        ) : !specs.data || specs.data.length === 0 ? (
          <EmptyState title="No fabric specifications" />
        ) : (
          <Table
            caption="Fabric specifications"
            head={["Code", "Fabric", "Composition", "Construction", "GSM", "Width", "Shade", "Finish", "Sold in"]}
          >
            {specs.data.map((spec) => (
              <tr key={spec.id}>
                <Td className="font-mono text-xs">{spec.code}</Td>
                <Td className="font-medium text-ink-900">{spec.name}</Td>
                <Td className="text-xs">{spec.composition}</Td>
                <Td className="text-xs">{spec.construction ?? "—"}</Td>
                <Td numeric>{spec.gsm}</Td>
                <Td numeric>{spec.width_cm} cm</Td>
                <Td className="text-xs">
                  {spec.colour ?? "—"}
                  {spec.shade_code && (
                    <span className="block font-mono text-ink-500">{spec.shade_code}</span>
                  )}
                </Td>
                <Td className="text-xs">{humanise(spec.finish)}</Td>
                <Td className="text-xs font-medium">{spec.sale_unit}</Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Materials">
        {materials.loading && !materials.data ? (
          <Loading />
        ) : materials.error ? (
          <ErrorState error={materials.error} onRetry={materials.reload} />
        ) : !materials.data || materials.data.length === 0 ? (
          <EmptyState title="No materials" />
        ) : (
          <Table
            caption="Materials"
            head={["Code", "Material", "Category", "Stocked in", "Yarn count", "Standard cost", "Reorder point", ""]}
          >
            {materials.data.map((material) => (
              <tr key={material.id}>
                <Td className="font-mono text-xs">{material.code}</Td>
                <Td className="font-medium text-ink-900">{material.name}</Td>
                <Td className="text-xs">{humanise(material.category)}</Td>
                <Td className="text-xs font-medium">{material.base_unit}</Td>
                <Td className="text-xs" title="A yarn count, not a mass.">
                  {material.yarn_count_text ?? "—"}
                </Td>
                <Td numeric>{money(material.standard_cost, material.currency)}</Td>
                <Td numeric>{quantity(material.reorder_point, material.base_unit)}</Td>
                <Td>
                  <Link
                    href={`/inventory/${material.id}`}
                    className="text-xs text-ink-700 hover:underline"
                  >
                    Coverage →
                  </Link>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
