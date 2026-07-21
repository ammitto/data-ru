# frozen_string_literal: true

require 'yaml'
require 'date'
require 'pathname'

module AmmittoDataRU
  # Parser for Russian MFA sanctions announcement markdown files
  class AnnouncementParser
    COUNTRY_CODES = {
      /США|United States|American/i => 'US',
      /Великобритан|United Kingdom|British/i => 'GB',
      /Канад|Canada|Canadian/i => 'CA',
      /Австрали|Australia|Australian/i => 'AU',
      /Япон|Japan|Japanese/i => 'JP',
      /Украин/i => 'UA',
      /Нов[ао]я Зеланди|New Zealand/i => 'NZ',
      /Швейцар|Switzerland|Swiss/i => 'CH',
      /Норвег|Norway|Norwegian/i => 'NO',
      /Сингапур|Singapore/i => 'SG',
      /Южн[ао]я Коре|South Korea|Korean/i => 'KR',
      /Франци|France|French/i => 'FR',
      /Герман|Germany|German/i => 'DE',
      /Итали|Italy|Italian/i => 'IT',
      /Польш|Poland|Polish/i => 'PL',
      /Финлянди|Finland|Finnish/i => 'FI',
      /Швеци|Sweden|Swedish/i => 'SE',
      /Чехи|Czech/i => 'CZ',
      /Румун|Romania/i => 'RO',
      /Болгари|Bulgaria/i => 'BG',
      /Латви|Latvia/i => 'LV',
      /Литв|Lithuania/i => 'LT',
      /Эстон|Estonia/i => 'EE',
      /Дани|Denmark/i => 'DK',
      /Нидерланд|Netherlands|Dutch/i => 'NL',
      /Бельг|Belgium/i => 'BE',
      /Ирланд|Ireland/i => 'IE',
      /Австри|Austria/i => 'AT',
      /Греци|Greece/i => 'GR',
      /Португал|Portugal/i => 'PT',
      /Испан|Spain/i => 'ES',
      /Словак|Slovakia/i => 'SK',
      /Словен|Slovenia/i => 'SI',
      /Хорват|Croatia/i => 'HR',
      /Микронези|Micronesia/i => 'FM'
    }.freeze

    ENGLISH_MONTHS = {
      'January' => 1, 'February' => 2, 'March' => 3, 'April' => 4,
      'May' => 5, 'June' => 6, 'July' => 7, 'August' => 8,
      'September' => 9, 'October' => 10, 'November' => 11, 'December' => 12
    }.freeze

    attr_reader :source_file

    def initialize(verbose: false)
      @verbose = verbose
      @source_file = nil
    end

    def parse(markdown_content, source_file: nil)
      @source_file = source_file
      sections = split_sections(markdown_content)
      ru_section = parse_section(sections[:russian], :ru)
      en_section = parse_section(sections[:english], :en)
      build_data_structure(ru_section, en_section, sections[:url])
    end

    def to_yaml(data)
      yaml_comment = "# yaml-language-server: $schema=../../schemas/announcement-schema.yml\n"
      string_key_data = deep_stringify_keys(data)
      yaml_output = string_key_data.to_yaml(line_width: 120)
      # Post-process to quote string values containing colons followed by space
      # This fixes YAML parsing issues with text like "Company: Subsidiary"
      # Pattern: after a key like "ru:" or "en:", quote the value if it contains ": "
      yaml_output.gsub!(/^( +)(ru|en): (.+): (.+)$/, '\1\2: "\3: \4"')
      yaml_comment + yaml_output
    end

    def parse_file(input_path, output_path: nil)
      input = Pathname.new(input_path)
      output = output_path ? Pathname.new(output_path) : input.sub_ext('.yml')

      markdown_content = input.read
      data = parse(markdown_content, source_file: input.basename.to_s)
      yaml_content = to_yaml(data)
      output.write(yaml_content)
      log "Parsed: #{input} -> #{output}"
      output.to_s
    end

    def parse_directory(directory)
      dir = Pathname.new(directory)
      md_files = dir.glob('*.md').sort
      md_files.map { |input| parse_file(input) }
    end

    private

    def split_sections(content)
      lines = content.lines.map(&:chomp)
      url = lines.first&.strip || ''
      ru_start = lines.index { |l| l.strip == '## Russian' }
      en_start = lines.index { |l| l.strip == '## English' }
      {
        url: url,
        russian: if ru_start
                   lines[(ru_start + 1)..(en_start ? en_start - 1 : -1)]
                 else
                   []
                 end,
        english: en_start ? lines[(en_start + 1)..] : []
      }
    end

    def parse_section(lines, lang)
      return { date_time: {}, title: '', document_id: '', preamble: '', entities: [] } if lines.nil? || lines.empty?

      lines = lines.dup
      date_time, lines = extract_date_time(lines, lang)
      title, lines = extract_title(lines)
      document_id, lines = extract_document_id(lines)
      preamble, entity_lines = split_preamble_and_entities(lines)
      entities = parse_entities(entity_lines, lang)
      {
        date_time: date_time,
        title: title,
        document_id: document_id,
        preamble: preamble,
        entities: entities
      }
    end

    def extract_date_time(lines, lang)
      lines = lines.dup
      lines.shift while lines.first&.strip&.empty?
      date_line = lines.shift&.strip || ''
      if lang == :ru
        match = date_line.match(/(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})/)
        return [{ date: "#{match[3]}-#{match[2]}-#{match[1]}", time: "#{match[4]}:#{match[5]}" }, lines] if match
      else
        match = date_line.match(/(\d{1,2})\s+(#{ENGLISH_MONTHS.keys.join('|')})\s+(\d{4})\s+(\d{2}):(\d{2})/i)
        if match
          return [
            { date: "#{match[3]}-#{ENGLISH_MONTHS[match[2]].to_s.rjust(2, '0')}-#{match[1].rjust(2, '0')}",
              time: "#{match[4]}:#{match[5]}" }, lines
          ]
        end
      end
      [{ date: nil, time: nil }, lines]
    end

    def extract_title(lines)
      lines = lines.dup
      lines.shift while lines.first&.strip&.empty?
      title = lines.shift&.strip || ''
      [title, lines]
    end

    def extract_document_id(lines)
      lines = lines.dup
      lines.shift while lines.first&.strip&.empty?
      doc_id = lines.shift&.strip || ''
      [doc_id, lines]
    end

    def split_preamble_and_entities(lines)
      return ['', []] if lines.nil? || lines.empty?

      preamble_lines = []
      entity_lines = []
      in_entities = false
      lines.each do |line|
        stripped = line.strip
        next if preamble_lines.empty? && stripped.empty?

        in_entities = true if !in_entities && entity_list_start?(stripped)
        if in_entities
          entity_lines << line
        else
          preamble_lines << line
        end
      end
      [clean_preamble(preamble_lines), entity_lines]
    end

    def entity_list_start?(line)
      return false if line.empty?
      # Lines starting with spaces are likely titles, not entity start
      return false if line.match?(/^\s+/)
      return true if line.match?(%r{^№\s*п/п$})
      return true if line.match?(/^Имя,\s*фамилия/)
      return true if line.match?(/^\d+$/)
      return true if line.match?(/^\d+\.\s/)
      # For Russian format: Name (English) - title
      return true if line.match?(/^[^(]+\([^)]+\)\s*[–-]/)
      return true if line.match?(/^[^(]+\([^)]+\)\s*;/)

      # For parenthesis at end, make sure it looks like a name, not a title
      # Titles often contain: Senator, Minister, Secretary, President, etc.
      if line.match?(/^[^(]+\([^)]+\)\s*$/)
        return false if line.match?(/Senator|Minister|Secretary|President|Member|Former|Assistant|Deputy/i)

        return true
      end
      # Russian name pattern
      return true if line.match?(/^[А-ЯЁ][а-яё]+\s+[А-ЯЁ]{3,}(?:\s|$)/)

      # English name pattern: First Last (at least two capitalized words)
      # But exclude lines that look like titles/headers
      if line.match?(/^[A-Z][a-z]+ [A-Z][a-z]+/)
        # Exclude lines that look like titles, headers, or preamble
        return false if line.match?(/Ministry|Statement|Announcement|Foreign|Affairs|Response|List|Complete/i)
        return false if line.match?(/In response|The list|A complete|Below is/i)

        return true
      end

      false
    end

    def clean_preamble(lines)
      lines = lines.dup
      lines.pop while lines.last&.strip&.empty?
      text = lines.join("\n")
      text = text.gsub(/\n\nНиже следует[^\n]*:\s*$/i, '')
      text = text.gsub(/\n\nTheir list follows[^\n]*:\s*$/i, '')
      text = text.gsub(/\n\nBelow is[^\n]*:\s*$/i, '')
      text = text.gsub(/\n\nСписок[^\n]*:$/i, '')
      text = text.gsub(/\n\nThe list is as follows:\s*$/i, '')
      "#{text.strip}\n\n<list>\n"
    end

    def parse_entities(lines, lang)
      return [] if lines.nil? || lines.empty?

      format = detect_entity_format(lines, lang)
      case format
      when :multiline then parse_multiline_entities(lines, lang)
      when :numbered_single then parse_numbered_single_entities(lines, lang)
      when :semicolon then parse_semicolon_entities(lines, lang)
      when :table then parse_table_entities(lines, lang)
      when :english_numbered then parse_english_numbered_entities(lines, lang)
      when :english_simple then parse_english_simple_entities(lines, lang)
      else parse_generic_entities(lines, lang)
      end
    end

    def detect_entity_format(lines, lang = :ru)
      sample = lines.take(50).join("\n")
      return :multiline if sample.include?("\n\n–\n\n") || sample.include?("\n\n-\n\n")
      return :numbered_single if sample.match?(/^\d+\.\s+[^(]+\([^)]+\)\s*[–-]/)
      return :table if sample.match?(/^\d+\s*\n\s*[A-Z][a-z]+\s+[A-Z]/m)
      return :english_numbered if sample.match?(/^\d+\.\s+[A-Z][^;(]+\s*[,;]/)
      return :semicolon if sample.include?(';') && sample.match?(/\([^)]+\)\s*[;,]/)
      # English simple format: name line, title line, blank line
      return :english_simple if lang == :en && sample.match?(/^[A-Z][a-z]+ [A-Z][a-z]+.*\n[A-Z][a-z]/m)

      :generic
    end

    def parse_multiline_entities(lines, _lang)
      entities = []
      text = lines.join("\n")
      dash_pattern = /\n\n[–-]\n\n/
      parts = text.split(dash_pattern)
      current_name = nil
      current_name_en = nil
      parts.each_with_index do |part, idx|
        part = part.strip
        next if part.empty?

        if idx.zero?
          current_name, current_name_en = extract_name_from_block(part)
        else
          sub_parts = part.split(/\n\n/, 2)
          title = sub_parts[0].strip if sub_parts[0] && !sub_parts[0].strip.empty?
          if current_name || current_name_en
            entities << { name_ru: current_name, name_en: current_name_en, title_ru: title, title_en: nil }
          end
          current_name, current_name_en = sub_parts[1] ? extract_name_from_block(sub_parts[1].strip) : [nil, nil]
        end
      end
      entities
    end

    def parse_numbered_single_entities(lines, _lang)
      entities = []
      text = lines.join("\n")
      pattern = /(\d+)\.\s+([^(]+)\(([^)]+)\)\s*[–-]\s*([^;\n]+)/
      text.scan(pattern) do |match|
        _num, name_ru, name_en, title = match
        entities << { name_ru: name_ru.strip, name_en: name_en.strip, title_ru: title.strip, title_en: nil }
      end
      entities
    end

    def parse_semicolon_entities(lines, _lang)
      entities = []
      text = lines.join("\n")
      # Pattern with dash separator (Russian format): Name (English) – title;
      pattern_with_dash = /([^(]+)\(([^)]+)\)\s*[–-]\s*([^;\n]+)/
      text.scan(pattern_with_dash) do |match|
        name_ru, name_en, title = match
        entities << { name_ru: name_ru.strip, name_en: name_en.strip, title_ru: title.strip, title_en: nil }
      end
      # Pattern with comma separator (English format): Name (Party, State), title;
      if entities.empty?
        pattern_with_comma = /(\d+)\.\s+([^(]+)\(([^)]+)\)\s*,\s*([^;\n]+)/
        text.scan(pattern_with_comma) do |match|
          _num, name_en, _party_state, title = match
          entities << { name_ru: nil, name_en: name_en.strip, title_ru: nil, title_en: title.strip }
        end
      end
      # Pattern name only with semicolon: Name (English);
      if entities.empty?
        pattern_name_only = /([^(]+)\(([^)]+)\)\s*;/
        text.scan(pattern_name_only) do |match|
          name_ru, name_en = match
          entities << { name_ru: name_ru.strip, name_en: name_en.strip, title_ru: nil, title_en: nil }
        end
      end
      entities
    end

    def parse_table_entities(lines, _lang)
      entities = []
      text = lines.join("\n")
      blocks = text.split(/^\s*(\d+)\s*\n/)
      (1..blocks.length - 1).step(2).each do |i|
        next if i + 1 >= blocks.length

        _num = blocks[i]
        content = blocks[i + 1]
        lines_in_block = content.split("\n").map(&:strip).reject(&:empty?)
        next if lines_in_block.length < 2

        name_en = nil
        name_ru = nil
        title_parts = []
        lines_in_block.each do |line|
          if name_en.nil? && line.match?(/^[A-Z][a-z]/)
            name_en = line
          elsif name_en && name_ru.nil? && line.match?(/^[А-ЯЁ][а-яё]/)
            name_ru = line
          elsif name_ru
            title_parts << line
          end
        end
        next unless name_en && name_ru

        title = title_parts.join(' ').strip
        title = nil if title.empty?
        entities << { name_ru: name_ru, name_en: name_en, title_ru: title, title_en: nil }
      end
      entities
    end

    def parse_english_numbered_entities(lines, _lang)
      entities = []
      text = lines.join("\n")
      # Pattern: "1. Name (Party, State), title;" or "1. Name, title;"
      pattern = /(\d+)\.\s+([A-Z][^;,]+)\s*[;,]\s*([^;\n]+)/
      text.scan(pattern) do |match|
        _num, name, title = match
        name = name.strip.gsub(/[,;]\s*$/, '')
        title = title.strip.gsub(/[,;]\s*$/, '')
        entities << { name_ru: nil, name_en: name, title_ru: nil, title_en: title }
      end
      entities
    end

    def parse_english_simple_entities(lines, _lang)
      # Format: Name line, Title line, blank line
      # e.g., "Jill Tracy Jacobs Biden\nThe wife of US President Joe Biden\n\n"
      entities = []
      text = lines.join("\n")
      # Split by double newlines to get entity blocks
      blocks = text.split(/\n\n+/)
      blocks.each do |block|
        lines_in_block = block.split("\n").map(&:strip).reject(&:empty?)
        next if lines_in_block.length < 2

        # First line is the name, rest is title
        name = lines_in_block[0]
        title = lines_in_block[1..].join(' ')
        # Skip if name doesn't look like a person name (starts with capital, has space)
        next unless name.match?(/^[A-Z][a-z]+ [A-Z]/)
        # Skip if title looks like it's preamble text (too long, contains certain keywords)
        next if title.length > 200 || title.match?(/^(In response|A complete|Their list)/i)

        entities << { name_ru: nil, name_en: name, title_ru: nil, title_en: title }
      end
      entities
    end

    def parse_generic_entities(lines, _lang)
      entities = []
      text = lines.join("\n")
      pattern = /([^(]+)\(([^)]+)\)/
      text.scan(pattern) do |match|
        name_ru, name_en = match
        name_ru = name_ru.strip.gsub(/^[,\s]+/, '').gsub(/[,\s]+$/, '')
        name_en = name_en.strip.gsub(/^[,\s]+/, '').gsub(/[,\s]+$/, '')
        entities << { name_ru: name_ru, name_en: name_en, title_ru: nil, title_en: nil }
      end
      entities
    end

    def extract_name_from_block(block)
      match = block.match(/([^(]+)\(([^)]+)\)/)
      return [match[1].strip, match[2].strip] if match

      lines = block.split("\n").map(&:strip).reject(&:empty?)
      return [lines[0], lines[1][1..-2]] if lines.length >= 2 && lines[1].start_with?('(') && lines[1].end_with?(')')

      [block.strip, nil]
    end

    def detect_country_code(title, content = nil)
      text = [title, content].compact.join(' ')
      COUNTRY_CODES.each { |pattern, code| return code if text.match?(pattern) }
      'XX'
    end

    def build_data_structure(ru_section, en_section, url)
      date = ru_section[:date_time][:date] || en_section[:date_time][:date]
      time = ru_section[:date_time][:time] || en_section[:date_time][:time]
      document_id = ru_section[:document_id] || en_section[:document_id]
      entities = merge_entities(ru_section[:entities], en_section[:entities])
      country_code = detect_country_code("#{ru_section[:title]} #{en_section[:title]}")
      reason = build_reason(country_code)
      measures = build_measures

      entity_list = entities.map do |entity|
        title_ru = entity[:title_ru]&.strip.to_s
        title_ru = 'без должности' if title_ru.nil? || title_ru.empty?
        title_en = entity[:title_en]&.strip.to_s
        title_en = entity[:title_ru] if title_en.nil? || title_en.empty?
        title_en = 'no title' if title_en.nil? || title_en.empty?
        {
          name: { ru: entity[:name_ru] || '', en: entity[:name_en] || '' },
          type: 'individual',
          nationality: country_code,
          title: { ru: title_ru, en: title_en },
          effective_date: date,
          sanction_list: 'черного списка',
          reason: [reason],
          measures: measures
        }
      end

      en_title = en_section[:title]
      en_title = ru_section[:title] if en_title.nil? || en_title.empty?

      {
        announcement: {
          title: { ru: ru_section[:title] || '', en: en_title || '' },
          url: url,
          lang: 'ru',
          publish_date: date,
          publish_time: time,
          authority: 'ru/ministry-of-foreign-affairs',
          publisher: 'ru/ministry-of-foreign-affairs',
          type: 'ru/ministry-of-foreign-affairs-announcement',
          document_id: document_id,
          signatory: 'ru/ministry-of-foreign-affairs',
          content: { ru: ru_section[:preamble] || '', en: en_section[:preamble] || '' }
        },
        sanction_details: {
          instruments: [{ id: 'ru/federal-law-114' }],
          entities: entity_list
        }
      }
    end

    def merge_entities(ru_entities, en_entities)
      ru_entities ||= []
      en_entities ||= []
      return [] if ru_entities.empty?

      en_lookup = {}
      en_entities.each do |entity|
        next unless entity[:name_en]

        key = normalize_name(entity[:name_en])
        en_lookup[key] = entity
      end
      ru_entities.map do |entity|
        next unless entity[:name_en]

        key = normalize_name(entity[:name_en])
        en_entity = en_lookup[key]
        entity[:title_en] = en_entity[:title_en] if en_entity && en_entity[:title_en]
        entity
      end
    end

    def normalize_name(name)
      return nil if name.nil?

      name.to_s.downcase.gsub(/[,.-]/, '').gsub(/\s+/, ' ').strip
    end

    def build_reason(country_code)
      reasons = {
        'US' => { ru: 'За участие в формировании русофобского курса США.',
                  en: 'For participation in formulating the Russophobic policy of the United States.' },
        'GB' => { ru: 'За сотрудничество с деструктивными британскими аналитическими и консалтинговыми центрами.',
                  en: 'For collaborating with destructive British analytical and consulting agencies.' },
        'CA' => { ru: 'За участие в антироссийской деятельности канадского правительства.',
                  en: 'For participation in anti-Russian activities of the Canadian government.' },
        'AU' => { ru: 'За участие в антироссийской деятельности австралийского правительства.',
                  en: 'For participation in anti-Russian activities of the Australian government.' },
        'JP' => { ru: 'За участие в антироссийской деятельности японского правительства.',
                  en: 'For participation in anti-Russian activities of the Japanese government.' },
        'NZ' => { ru: 'За антироссийскую деятельность.', en: 'For anti-Russian activities.' }
      }
      reasons[country_code] || { ru: 'За сотрудничество с антироссийскими силами.',
                                 en: 'For collaboration with anti-Russian forces.' }
    end

    def build_measures
      [{ type: ['entry_ban'], ru: 'Запрещен въезд в Российскую Федерацию.',
         en: 'Entry into the Russian Federation is prohibited.' }]
    end

    def deep_stringify_keys(obj)
      case obj
      when Hash
        obj.transform_keys(&:to_s).transform_values { |v| deep_stringify_keys(v) }
      when Array
        obj.map { |v| deep_stringify_keys(v) }
      else
        obj
      end
    end

    def log(message)
      puts message if @verbose
    end
  end
end
