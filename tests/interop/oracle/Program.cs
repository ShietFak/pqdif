// Test-only adapter to the actual GPA library. See licenses/Gemstone-MIT.txt.
using System.Text.Json;
using Gemstone.PQDIF.Logical;
using Gemstone.PQDIF.Physical;

static class Program
{
    static readonly Guid Vendor = new("a1111111-2222-3333-4444-555555555555");
    static readonly DateTime Stamp = new(2026, 1, 2, 3, 4, 5, DateTimeKind.Utc);

    static async Task Main(string[] args)
    {
        if (args.Length < 2) throw new ArgumentException("generate|inspect|rewrite PATH [MODE|TARGET]");
        if (args[0] == "generate") await Generate(args[1], args[2] == "zlib");
        else if (args[0] == "rewrite") await Rewrite(args[1], args[2]);
        else if (args[0] != "inspect") throw new ArgumentException("Unknown command");
        string path = args[0] == "rewrite" ? args[2] : args[1];
        Console.WriteLine(JsonSerializer.Serialize(await Inspect(path)));
    }

    static ScalarElement RawScalar(PhysicalType kind, string hex)
    {
        ScalarElement result = new() { TagOfElement = Vendor, TypeOfValue = kind };
        result.SetValue(Convert.FromHexString(hex), 0);
        return result;
    }

    static void AddPhysicalTypeCorpus(CollectionElement root)
    {
        CollectionElement nested = new() { TagOfElement = Vendor };
        (PhysicalType kind, string raw)[] cases = [
            (PhysicalType.Boolean1, "ff"), (PhysicalType.Boolean2, "ffff"),
            (PhysicalType.Boolean4, "ffffffff"), (PhysicalType.Char1, "41"),
            (PhysicalType.Char2, "a903"), (PhysicalType.Integer1, "fe"),
            (PhysicalType.Integer2, "feff"), (PhysicalType.Integer4, "feffffff"),
            (PhysicalType.UnsignedInteger1, "ff"), (PhysicalType.UnsignedInteger2, "ffff"),
            (PhysicalType.UnsignedInteger4, "ffffffff"), (PhysicalType.Real4, "0100c07f"),
            (PhysicalType.Real8, "000000000000f83f"),
            (PhysicalType.Complex8, "0000803f000000c0"),
            (PhysicalType.Complex16, "000000000000f03f00000000000000c0"),
            (PhysicalType.Timestamp, "c8af00005f633937dd9abf3f"),
            (PhysicalType.Guid, "44332211665588779900aabbccddeeff")
        ];
        foreach (var (kind, raw) in cases)
        {
            nested.AddElement(RawScalar(kind, raw));
            VectorElement vector = new() { TagOfElement = Vendor, TypeOfValue = kind, Size = 2 };
            vector.SetValues(Convert.FromHexString(raw + raw), 0);
            nested.AddElement(vector);
        }
        nested.AddElement(new CollectionElement { TagOfElement = Vendor });
        root.AddElement(nested);
    }

    static async Task Generate(string path, bool compressed)
    {
        ContainerRecord container = ContainerRecord.CreateContainerRecord();
        container.FileName = "gemstone-fixture.pqd";
        container.Creation = Stamp;
        container.CompressionStyle = compressed ? CompressionStyle.RecordLevel : CompressionStyle.None;
        container.CompressionAlgorithm = compressed ? CompressionAlgorithm.Zlib : CompressionAlgorithm.None;
        AddPhysicalTypeCorpus(container.PhysicalRecord.Body.Collection);

        DataSourceRecord source = DataSourceRecord.CreateDataSourceRecord("Gemstone oracle");
        source.Effective = Stamp;
        ChannelDefinition channel = source.AddNewChannelDefinition();
        channel.ChannelName = "Va";
        channel.Phase = (Phase)1;
        channel.QuantityTypeID = QuantityType.WaveForm;
        channel.QuantityMeasured = QuantityMeasured.Voltage;
        SeriesDefinition definition = channel.AddNewSeriesDefinition();
        definition.QuantityUnits = QuantityUnits.Volts;
        definition.QuantityCharacteristicID = QuantityCharacteristic.Instantaneous;
        SeriesDefinition scaledDefinition = channel.AddNewSeriesDefinition();
        scaledDefinition.QuantityUnits = QuantityUnits.Volts;
        scaledDefinition.StorageMethodID = StorageMethods.Values | StorageMethods.Scaled;
        SeriesDefinition incrementDefinition = channel.AddNewSeriesDefinition();
        incrementDefinition.QuantityUnits = QuantityUnits.Seconds;
        incrementDefinition.StorageMethodID = StorageMethods.Increment;
        ObservationRecord observation = ObservationRecord.CreateObservationRecord(source, null);
        observation.Name = "Gemstone event";
        observation.StartTime = Stamp;
        observation.CreateTime = Stamp;
        ChannelInstance instance = observation.AddNewChannelInstance(channel);
        SeriesInstance series = instance.AddNewSeriesInstance();
        series.SetValues(new object[] { 0.25, -1.5, 3.75 });
        SeriesInstance scaled = instance.AddNewSeriesInstance();
        scaled.SetValues(new object[] { (short)1, (short)2, (short)3 });
        ScalarElement scale = new() { TypeOfValue = PhysicalType.Integer2 };
        scale.SetInt2(2);
        scaled.SeriesScale = scale;
        ScalarElement offset = new() { TypeOfValue = PhysicalType.Integer2 };
        offset.SetInt2(-1);
        scaled.SeriesOffset = offset;
        SeriesInstance increment = instance.AddNewSeriesInstance();
        increment.SetValues(new object[] { 1.0, 4.0, 0.25 });
        await using LogicalWriter writer = new(path);
        await writer.WriteAsync(container);
        await writer.WriteAsync(observation, true);
        if (writer.MissingTags.Count != 0) throw new InvalidDataException("Generator omitted required tags");
    }

    static async Task<List<Record>> PhysicalRecords(string path)
    {
        List<Record> records = [];
        await using PhysicalParser parser = new(path);
        await parser.OpenAsync();
        while (parser.HasNextRecord())
        {
            Record record = await parser.GetNextRecordAsync();
            records.Add(record);
            if (record.Header.Checksum != 0 && record.Header.Checksum != record.Body.Checksum)
                throw new InvalidDataException("Checksum mismatch in oracle");
            if (records.Count == 1)
            {
                ContainerRecord container = ContainerRecord.CreateContainerRecord(record)!;
                parser.CompressionStyle = container.CompressionStyle;
                parser.CompressionAlgorithm = container.CompressionAlgorithm;
            }
        }
        if (parser.ExceptionList.Count != 0)
            throw new AggregateException("Gemstone parsing errors", parser.ExceptionList);
        return records;
    }

    static object Canonical(Element element)
    {
        if (element is CollectionElement collection)
            return new { tag = element.TagOfElement.ToString(), kind = 1,
                         type = (int)element.TypeOfValue,
                         children = collection.Elements.Select(Canonical).ToArray() };
        byte[] bytes = element is ScalarElement scalar ? scalar.GetValue() : ((VectorElement)element).GetValues();
        return new { tag = element.TagOfElement.ToString(), kind = (int)element.TypeOfElement,
                     type = (int)element.TypeOfValue, raw = Convert.ToHexString(bytes).ToLowerInvariant() };
    }

    static async Task<object> Inspect(string path)
    {
        List<Record> records = await PhysicalRecords(path);
        List<ObservationRecord> observations = [];
        await using LogicalParser logical = new(path);
        await logical.OpenAsync();
        while (await logical.HasNextObservationRecordAsync())
            observations.Add(await logical.NextObservationRecordAsync());
        await using LogicalWriter validator = new(new MemoryStream());
        await validator.WriteAsync(logical.ContainerRecord!);
        foreach (ObservationRecord observation in observations) await validator.WriteAsync(observation);
        double[] values = observations.Count == 0 ? [] : observations[0].ChannelInstances[0]
            .SeriesInstances[0].OriginalValues.Select(Convert.ToDouble).ToArray();
        double[][][][] seriesValues = observations.Select(observation => observation.ChannelInstances
            .Select(channel => channel.SeriesInstances.Select(series => series.OriginalValues
                .Select(Convert.ToDouble).ToArray()).ToArray()).ToArray()).ToArray();
        return new { records = records.Select(r => new { tag = r.Header.RecordTypeTag.ToString(),
                                                         body = Canonical(r.Body.Collection) }).ToArray(),
                     values, seriesValues,
                     missingTags = validator.MissingTags.Select(m => m.TagName).ToArray() };
    }

    static async Task Rewrite(string source, string target)
    {
        List<Record> records = await PhysicalRecords(source);
        await using PhysicalWriter writer = new(target);
        for (int i = 0; i < records.Count; i++)
        {
            await writer.WriteRecordAsync(records[i], i == records.Count - 1);
            if (i == 0)
            {
                ContainerRecord container = ContainerRecord.CreateContainerRecord(records[i])!;
                writer.CompressionStyle = container.CompressionStyle;
                writer.CompressionAlgorithm = container.CompressionAlgorithm;
            }
        }
    }
}
