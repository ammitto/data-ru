# frozen_string_literal: true

# Reconstruct data-ru's per-entity source YAML from the ru.jsonld that
# ammitto/data already publishes. The February 2026 corpus that produced
# it is gone, but the harmonizer preserved every source-specific field it
# consumed under raw_source_data, so the input is derivable from the
# output. Whether that derivation is faithful is settled by re-harmonizing
# and diffing, not by this script's own say-so.

require 'json'
require 'yaml'
require 'fileutils'

graph_path = ARGV[0] or abort 'usage: reconstruct_ru.rb <ru.jsonld> <outdir>'
out_dir    = ARGV[1] or abort 'usage: reconstruct_ru.rb <ru.jsonld> <outdir>'

doc   = JSON.parse(File.read(graph_path))
nodes = doc['@graph'] || doc

entities = {}
entries  = {}
nodes.each do |n|
  if n.key?('raw_source_data')
    entries[n['entity_id']] = n
  else
    entities[n['id']] = n
  end
end

FileUtils.mkdir_p(out_dir)

written = 0
skipped = []

entities.each do |id, entity|
  entry = entries[id]
  if entry.nil?
    skipped << [id, 'no paired entry node']
    next
  end

  fields = entry.dig('raw_source_data', 'source_specific_fields') || {}
  names  = entity['names'] || []

  latin = names.find { |n| n['script'] == 'Latn' && n['is_primary'] } ||
          names.find { |n| n['script'] == 'Latn' }
  cyril = names.find { |n| n['script'] == 'Cyrl' }

  record = {
    'russian_name' => fields['ru:russian_name'] || cyril&.dig('full_name'),
    'english_name' => latin&.dig('full_name'),
    'entity_type'  => entity['entity_type'],
    'list_type'    => fields['ru:list_type'],
    'title'        => fields['ru:title'],
    'nationality'  => (entity['nationalities'] || []).first,
    'country'      => fields['ru:country'],
    'industry'     => fields['ru:industry'],
    'affiliation'  => fields['ru:affiliation'],
  }.compact

  if record['english_name'].nil? && record['russian_name'].nil?
    skipped << [id, 'no usable name']
    next
  end

  # Name the file after the reference the harmonizer already assigned, so
  # a rerun overwrites rather than accumulating near-duplicates. Anything
  # a filesystem would choke on becomes an underscore.
  ref  = entry['reference_number'] || id.split('/').last
  slug = ref.gsub(%r{[/\\:*?"<>|\s]+}, '_').gsub(/_+/, '_').sub(/\A_/, '')
  File.write(File.join(out_dir, "#{slug}.yaml"), record.to_yaml)
  written += 1
end

warn "entities=#{entities.size} entries=#{entries.size} written=#{written} skipped=#{skipped.size}"
skipped.first(5).each { |id, why| warn "  skipped #{id}: #{why}" }
