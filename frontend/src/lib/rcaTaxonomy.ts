import type { RcaOptions } from '../types/rca';

/**
 * The approved RCA taxonomy as the server sends it (apps.rca.taxonomy, in the RCA options). The pages keep no list of
 * their own: every Final Bucket and Sub Bucket dropdown is built from these helpers.
 */
export const approvedFinalBuckets = (options: Pick<RcaOptions, 'classification'>): string[] =>
  (options.classification ?? []).map((c) => c.final_bucket);

/** The approved Sub Buckets of one Final Bucket (none for an unknown or empty Final Bucket). */
export const approvedSubBuckets = (options: Pick<RcaOptions, 'classification'>, finalBucket: string): string[] =>
  (options.classification ?? []).find((c) => c.final_bucket === finalBucket)?.bucket_2 ?? [];
