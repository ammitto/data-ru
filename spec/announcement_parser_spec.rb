# frozen_string_literal: true

require 'spec_helper'
require 'ammitto-data-ru/announcement_parser'

RSpec.describe AmmittoDataRU::AnnouncementParser do
  let(:parser) { AmmittoDataRU::AnnouncementParser.new(verbose: true) }

  describe '#parse' do
    context 'with a simple entity list (20220628.md format)' do
      let(:content) { File.read(fixture_path('fixtures/20220628.md')) }
      let(:data) { parser.parse(content, source_file: '20220628.md') }

      it 'extracts announcement metadata' do
        expect(data[:announcement]).not_to be_empty
        expect(data[:announcement][:title][:ru]).to include('Заявление МИД России')
        expect(data[:announcement][:title][:en]).to include('Foreign Ministry')
        expect(data[:announcement][:url]).to eq('https://www.mid.ru/ru/foreign_policy/news/1819686/')
        expect(data[:announcement][:publish_date]).to eq('2022-06-28')
        expect(data[:announcement][:document_id]).to eq('1345-28-06-2022')
      end

      it 'extracts entities from multiline format' do
        entities = data[:sanction_details][:entities]
        expect(entities.length).to eq(6)

        # Check first entity (Jill Biden)
        expect(entities[0][:name][:ru]).to include('БАЙДЕН')
        expect(entities[0][:name][:en]).to include('Jill')
        expect(entities[0][:title][:ru]).to include('супруга')

        # Check middle entity (Charles Grassley)
        expect(entities[2][:name][:ru]).to include('ГРАССЛИ')
        expect(entities[2][:name][:en]).to include('Grassley')
        expect(entities[2][:title][:ru]).to include('Сенат')

        # Check last entity (Benjamin Schmitt)
        expect(entities.last[:name][:ru]).to include('ШМИДТ')
        expect(entities.last[:name][:en]).to include('Schmidt')
      end
    end
  end
end
