# frozen_string_literal: true

require 'json'
require 'tmpdir'
require 'fileutils'
require_relative '../lib/ammitto-data-ru/schema_validator'

RSpec.describe AmmittoDataRU::SchemaValidator do
  it 'discovers canonical processed YAML and validates honest optional source fields' do
    Dir.mktmpdir do |directory|
      FileUtils.mkdir_p([File.join(directory, 'sources'), File.join(directory, 'processed'), File.join(directory, 'schemas')])
      FileUtils.cp(File.expand_path('../schemas/announcement-schema.yml', __dir__), File.join(directory, 'schemas/announcement-schema.yml'))
      data = {'announcement' => {'title' => {'ru' => 'Граждане под санкциями'}, 'url' => 'https://mid.ru/ru/detail-material-page/123/',
                                'lang' => 'ru', 'publish_date' => '2022-08-01', 'publish_time' => '10:37',
                                'content' => {'ru' => 'Официальный список граждан'}},
              'sanction_details' => {'entities' => [{'name' => {'ru' => 'Джон Смит', 'en' => 'John Smith'}, 'type' => 'individual'}]}}
      path = File.join(directory, 'processed/source.yml')
      File.write(path, JSON.generate(data))
      validator = described_class.new(root_dir: directory)
      expect(validator.yaml_files.map(&:to_s)).to eq([path])
      expect(validator.validate_file(path).errors).to eq([])
      data['sanction_details']['entities'][0]['type'] = 'unresolved'
      File.write(path, JSON.generate(data))
      expect(validator.validate_file(path).valid).to be(false)
    end
  end
end
