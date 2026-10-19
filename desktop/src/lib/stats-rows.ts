/** The most recent season's row: the last one before "Career" (rows run
 *  oldest first since 8.2.3); Career itself when there is no season. */
export function latestSeasonRow(
  rows: Array<[string, Record<string, unknown>]>,
): [string, Record<string, unknown>] | undefined {
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const row = rows[i];
    if (row && row[0] !== "Career") return row;
  }
  return rows[0];
}
