from pathlib import Path
from .base import ParserBase
from ..workout import Workout

class IGPSportParser(ParserBase):
    NAME = "IGPSPORT"
    FORMAT = "igpsport"
    FILE_EXT = "fit"

    def __init__(self, file_path: Path):
        super().__init__(file_path)

    def load(self) -> Workout:
        raise NotImplementedError("Loading .fit files for iGPSPORT is not yet implemented.")

    def save(self, workout: Workout):
        try:
            from fitencode import FitEncode, fields, messages
            from datetime import datetime
        except ImportError:
            raise ImportError(
                "fitencode library is required for IGPSPORT .fit export. Please install with: pip install git+https://github.com/hpcjc/python-fit-encode.\n"
            )

        # Define local message types for file_id, workout, workout_step
        # These may need to be adjusted based on IGPSPORT-specific requirements
        class LocalFileId(messages.FileId):
            manufacturer = fields.Uint16Field(field_def=1)
            type = fields.FileField(field_def=0)
            product = fields.Uint16Field(field_def=2)
            serial_number = fields.Uint32zField(field_def=3)

        class LocalWorkout(messages.Message):  # 26 = WORKOUT
            mesg_num = 26
            sport = fields.Uint8Field(field_def=4)
            capabilities = fields.Uint32Field(field_def=5)
            num_valid_steps = fields.Uint16Field(field_def=6)
            wkt_name = fields.StringField(field_def=8)

        class LocalWorkoutStep(messages.Message):  # 27 = WORKOUT_STEP
            mesg_num = 27
            message_index = fields.MessageIndexField(field_def=254)
            duration_type = fields.Uint8Field(field_def=0)
            duration_value = fields.Uint32Field(field_def=1)
            target_type = fields.Uint8Field(field_def=2)
            target_value = fields.Uint32Field(field_def=3)
            custom_target_value_low = fields.Uint32Field(field_def=4)
            custom_target_value_high = fields.Uint32Field(field_def=5)
            intensity = fields.Uint8Field(field_def=7)
            wkt_step_name = fields.StringField(field_def=8)

        # Prepare fit file
        with open(str(self._file_path), "bw") as f:
            fit = FitEncode(buffer=f)

            # FileId
            file_id = LocalFileId()
            fit.add_definition(file_id)
            fit.add_record(
                file_id.pack(
                    manufacturer=0x003C,  # 60 ("igpsport") or adjust as needed
                    type=0x04,  # workout
                    product=65534,
                    serial_number=12345678
                )
            )

            # Workout
            local_workout = LocalWorkout()
            fit.add_definition(local_workout)
            fit.add_record(
                local_workout.pack(
                    sport=2,  # cycling
                    capabilities=0,
                    num_valid_steps=sum([seg.repeat * len(seg.entries) for seg in workout.segments]),
                    wkt_name=(workout.name[:16] if workout.name else "Workout")
                )
            )

            # Steps
            msg_idx = 0
            inten_map = {
                "warmup": 0, "cooldown": 2, "interval": 1,
                "steadystate": 1, "freeride": 1, "ramp": 1
            }
            duration_type_map = {
                "time": 0,
            }
            target_type_map = {
                "power": 1,
                "heart_rate": 2,
                "open": 0
            }

            for seg in workout.segments:
                seg_intensity = inten_map.get(seg.type.value, 1)
                for rep in range(seg.repeat):
                    for entry in seg.entries:
                        tgt = entry.targets
                        # Default to open
                        target_type = "open"
                        target_value = 0
                        custom_target_value_low = 0
                        custom_target_value_high = 0

                        if "HEARTRATE" in tgt or "heart_rate" in tgt:
                            hr = tgt.get("HEARTRATE", None) or tgt.get("heart_rate", None)
                            if hr and hr.is_range():
                                target_type = "heart_rate"
                                custom_target_value_low = hr.low
                                custom_target_value_high = hr.high
                            elif hr and hr.value:
                                target_type = "heart_rate"
                                custom_target_value_low = custom_target_value_high = hr.value
                        elif "FTP_RELATIVE" in tgt:
                            pw = tgt.get("FTP_RELATIVE")
                            # Zwift FTP is a fraction: 0.65 = 65% FTP
                            if pw and pw.is_range():
                                target_type = "power"
                                # Both .low and .high are already scaled (int(100*V)), so set directly
                                custom_target_value_low = pw.low
                                custom_target_value_high = pw.high
                            elif pw and pw.value is not None:
                                target_type = "power"
                                # pw.value already int(100*ftp_fraction) (e.g. 75 for 0.75)
                                custom_target_value_low = custom_target_value_high = pw.value
                        elif "POWER" in tgt or "power" in tgt:
                            pw = tgt.get("POWER", None) or tgt.get("power", None)
                            if pw and pw.is_range():
                                target_type = "power"
                                custom_target_value_low = pw.low
                                custom_target_value_high = pw.high
                            elif pw and pw.value is not None:
                                target_type = "power"
                                custom_target_value_low = custom_target_value_high = pw.value

                        step_name = entry.name or seg.description or workout.name
                        duration = float(entry.duration)

                        workout_step = LocalWorkoutStep()
                        fit.add_definition(workout_step)
                        fit.add_record(
                            workout_step.pack(
                                message_index=msg_idx,
                                duration_type=duration_type_map["time"],
                                duration_value=int(duration),
                                target_type=target_type_map[target_type],
                                target_value=0,
                                custom_target_value_low=int(custom_target_value_low),
                                custom_target_value_high=int(custom_target_value_high),
                                intensity=seg_intensity,
                                wkt_step_name=(step_name[:16] if step_name else "")
                            )
                        )
                        msg_idx += 1
            fit.finish()
